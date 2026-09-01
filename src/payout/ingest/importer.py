"""Seed-workbook importer.

Reads the three-tab onboarding workbook (Roster / EV Register / Opening
Balances) and populates the database.

    preview_seed(workbook_bytes) -> SeedReport   # dry run, writes nothing
    import_seed(workbook_bytes)  -> SeedReport   # commits

The preview resolves references against the live DB inside a rolled-back
transaction, so its counts and warnings match exactly what a real import would
do. Re-importing skips riders / EVs / balances already present.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from io import BytesIO

import pandas as pd

from payout.db import get_connection
from payout.money import to_paise
from payout.parsers.base import match_column, read_table, to_float

_ROSTER_KEYS = ("roster",)
_EV_KEYS = ("ev register", "ev_register", "register")
_BAL_KEYS = ("opening", "balance", "dues")


@dataclass
class SeedReport:
    committed: bool
    stats: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)


def _cell(row, col):
    if not col:
        return None
    v = row.get(col)
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).strip()
    return s if s and s.lower() != "nan" else None


def _parse_date(val):
    if not val:
        return None
    ts = pd.to_datetime(str(val).strip(), dayfirst=True, errors="coerce")
    if not pd.isna(ts):
        return ts.date()
    try:
        serial = float(str(val).strip())
        if 30000 < serial < 80000:
            return date(1899, 12, 30) + timedelta(days=int(serial))
    except (ValueError, TypeError):
        pass
    return None


def _find_sheet(xl, keywords):
    for name in xl.sheet_names:
        low = name.strip().lower()
        if any(k in low for k in keywords):
            return name
    return None


def _init_person(conn, person_id):
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO balances (person_id, current_balance, last_updated) VALUES (?,0,?)",
        (person_id, now),
    )
    conn.execute(
        "INSERT OR IGNORE INTO status_tracking (person_id, status, ev_returned) VALUES (?, 'active', 0)",  # noqa: E501
        (person_id,),
    )
    conn.execute(
        "INSERT OR IGNORE INTO ev_arrears (person_id, total_missed, total_recovered, outstanding, last_updated) VALUES (?,0,0,0,?)",  # noqa: E501
        (person_id, now),
    )


def _resolve_person_by_name(conn, name, company, report, ctx):
    if company:
        rows = conn.execute(
            "SELECT DISTINCT person_id FROM rider_master WHERE LOWER(name)=LOWER(?) AND company=?",
            (name, company),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT DISTINCT person_id FROM rider_master WHERE LOWER(name)=LOWER(?)", (name,)
        ).fetchall()
    if not rows:
        report.warnings.append(
            f"{ctx}: rider '{name}'" + (f" @ {company}" if company else "") + " not in roster"
        )
        return None
    if len(rows) > 1:
        report.warnings.append(
            f"{ctx}: rider '{name}' ambiguous ({len(rows)} people) - needs company"
        )
        return None
    return rows[0]["person_id"]


def _import_roster(conn, xl, report):
    sheet = _find_sheet(xl, _ROSTER_KEYS)
    if not sheet:
        report.errors.append("No 'Roster' sheet found.")
        return
    df = read_table(xl, sheet, ["rider_id", "rider id", "riderid"])
    c = {
        "rid": match_column(df.columns, "rider_id", "rider id", "riderid"),
        "co": match_column(df.columns, "company"),
        "name": match_column(df.columns, "rider_name", "rider name", "name"),
        "hub": match_column(df.columns, "hub"),
        "veh": match_column(df.columns, "vehicle", "vehicle type"),
        "acc": match_column(df.columns, "account_no", "account no", "acc_no", "account number"),
        "ifsc": match_column(df.columns, "ifsc", "ifsc code"),
        "mob": match_column(
            df.columns, "mob_no", "mob no", "mobile", "phone", "phone no", "phone number"
        ),
    }
    missing = [k for k in ("rid", "co", "name") if not c[k]]
    if missing:
        report.errors.append(
            f"Roster missing required column(s) {missing}. Found: {list(df.columns)}"
        )
        return
    companies = {r["company_name"] for r in conn.execute("SELECT company_name FROM companies")}
    new_persons = new_riders = skipped = name_grouped = 0
    for _, row in df.iterrows():
        rid = _cell(row, c["rid"])
        name = _cell(row, c["name"])
        co = _cell(row, c["co"])
        if not rid or not name or not co:
            skipped += 1
            continue
        if co not in companies:
            report.warnings.append(f"Roster: unknown company '{co}' (rider {rid}) - skipped")
            skipped += 1
            continue
        if conn.execute(
            "SELECT 1 FROM rider_master WHERE rider_id=? AND company=?", (rid, co)
        ).fetchone():
            skipped += 1
            continue
        pr = conn.execute(
            "SELECT person_id FROM person_registry WHERE LOWER(display_name)=LOWER(?)", (name,)
        ).fetchone()
        if pr:
            person_id = pr["person_id"]
            name_grouped += 1
        else:
            cur = conn.execute(
                "INSERT INTO person_registry (display_name, deduction_company, deduction_rider_id) VALUES (?,?,?)",  # noqa: E501
                (name, co, rid),
            )
            person_id = cur.lastrowid
            _init_person(conn, person_id)
            new_persons += 1
        # Default any blank vehicle to BIKE so the inactive sheet and any
        # downstream raw exports have a consistent fallback.
        veh = (_cell(row, c["veh"]) or "BIKE").upper()
        # Phone: from the file if present; for Spencer's the rider_id IS the
        # phone number, so fall back to that.
        mob = _cell(row, c["mob"]) if c["mob"] else None
        if not mob and co and co.strip().lower().startswith("spencer"):
            mob = rid
        conn.execute(
            "INSERT INTO rider_master (rider_id, company, person_id, name, hub, vehicle, account_no, ifsc, mob_no) VALUES (?,?,?,?,?,?,?,?,?)",  # noqa: E501
            (
                rid,
                co,
                person_id,
                name,
                _cell(row, c["hub"]),
                veh,
                _cell(row, c["acc"]),
                _cell(row, c["ifsc"]),
                mob,
            ),
        )
        new_riders += 1
        if not _cell(row, c["acc"]) or not _cell(row, c["ifsc"]):
            report.warnings.append(f"Roster: {rid} ({name}) missing bank details")
    report.stats["roster"] = {
        "new_persons": new_persons,
        "new_riders": new_riders,
        "skipped": skipped,
        "name_grouped": name_grouped,
    }


def _import_ev(conn, xl, report):
    sheet = _find_sheet(xl, _EV_KEYS)
    if not sheet:
        report.warnings.append("No 'EV Register' sheet found - EVs skipped.")
        return
    df = read_table(xl, sheet, ["ev_id", "ev id", "evid"])
    c = {
        "ev": match_column(df.columns, "ev_id", "ev id", "evid"),
        "prov": match_column(df.columns, "provider"),
        "model": match_column(df.columns, "model"),
        "name": match_column(
            df.columns,
            "current_holder",
            "current holder",
            "current_rider_name",
            "rider_name",
            "rider name",
            "name",
        ),
        "co": match_column(df.columns, "company_billed", "company billed", "company"),
        "date": match_column(df.columns, "handover_date", "handover date", "handover"),
    }
    missing = [k for k in ("ev", "prov", "model") if not c[k]]
    if missing:
        report.errors.append(
            f"EV Register missing required column(s) {missing}. Found: {list(df.columns)}"
        )
        return
    # Lenient resolver: auto-create unknown (provider, model) entries instead
    # of silently rejecting them, so a fresh master roll-out (e.g. Raft's
    # "WARRIOR 2.0" / "WARRIOR 2.O" variants that aren't seeded) registers
    # the fleet on first import. Rate is copied from a sibling model under
    # the same provider; if nothing to copy from, the resolver flags it.
    from payout.domain.fleet_sync import resolve_or_create_model

    units = assigns = conflicts = bad_models = unresolved = 0
    models_created: list[str] = []
    rate_review: list[str] = []
    for _, row in df.iterrows():
        ev = _cell(row, c["ev"])
        prov = _cell(row, c["prov"])
        model = _cell(row, c["model"])
        if not ev or not prov or not model:
            continue
        try:
            res = resolve_or_create_model(conn, prov, model)
        except Exception as exc:
            report.warnings.append(f"EV {ev}: couldn't resolve '{prov}/{model}' ({exc}) - skipped")
            bad_models += 1
            continue
        if res.created:
            models_created.append(f"{prov}/{model}")
            if res.flagged_rate:
                rate_review.append(f"{prov}/{model}")
        if not conn.execute("SELECT 1 FROM ev_units WHERE ev_id=?", (ev,)).fetchone():
            conn.execute(
                "INSERT INTO ev_units (ev_id, model_id, status) VALUES (?,?, 'spare')",
                (ev, res.model_id),
            )
            units += 1
        name = _cell(row, c["name"])
        co = _cell(row, c["co"])
        if not name:
            continue
        person_id = _resolve_person_by_name(conn, name, co, report, f"EV {ev}")
        if person_id is None:
            unresolved += 1
            continue
        if conn.execute(
            "SELECT 1 FROM ev_assignments WHERE person_id=? AND returned_date IS NULL", (person_id,)
        ).fetchone():
            report.warnings.append(f"EV {ev}: {name} already holds an EV - conflict, not assigned")
            conflicts += 1
            continue
        if conn.execute(
            "SELECT 1 FROM ev_assignments WHERE ev_id=? AND returned_date IS NULL", (ev,)
        ).fetchone():
            report.warnings.append(f"EV {ev}: already assigned - skipped")
            continue
        hod = _parse_date(_cell(row, c["date"]))
        conn.execute(
            "INSERT INTO ev_assignments (person_id, ev_id, handover_date) VALUES (?,?,?)",
            (person_id, ev, hod.isoformat() if hod else None),
        )
        conn.execute("UPDATE ev_units SET status='in_use' WHERE ev_id=?", (ev,))
        assigns += 1
    report.stats["ev"] = {
        "units_added": units,
        "assignments": assigns,
        "conflicts": conflicts,
        "bad_models": bad_models,
        "unresolved": unresolved,
        "models_created": sorted(set(models_created)),
        "rate_review_needed": sorted(set(rate_review)),
    }
    if rate_review:
        report.warnings.append(
            "Auto-created models with placeholder rate (please set on rate card): "
            + ", ".join(sorted(set(rate_review)))
        )


def _import_balances(conn, xl, report, created_by):
    sheet = _find_sheet(xl, _BAL_KEYS)
    if not sheet:
        report.warnings.append("No 'Opening Balances' sheet found - skipped.")
        return
    df = read_table(xl, sheet, ["rider_id", "rider id", "riderid"])
    c = {
        "rid": match_column(df.columns, "rider_id", "rider id", "riderid"),
        "co": match_column(df.columns, "company"),
        "dues": match_column(df.columns, "opening_dues", "opening dues", "dues"),
        "arr": match_column(
            df.columns, "opening_ev_arrears", "opening ev arrears", "ev arrears", "arrears"
        ),
        "cod": match_column(
            df.columns,
            "opening_cod",
            "opening cod",
            "opening cod pending",
            "cod pending",
            "cod_pending",
            "cod",
        ),
    }
    if not c["rid"]:
        report.errors.append(f"Opening Balances missing 'rider_id'. Found: {list(df.columns)}")
        return
    applied = skipped = unresolved = 0
    seen = set()
    today = date.today().isoformat()
    for _, row in df.iterrows():
        rid = _cell(row, c["rid"])
        co = _cell(row, c["co"])
        if not rid:
            continue
        if co:
            pr = conn.execute(
                "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?", (rid, co)
            ).fetchone()
        else:
            rows = conn.execute(
                "SELECT DISTINCT person_id FROM rider_master WHERE rider_id=?", (rid,)
            ).fetchall()
            if len(rows) > 1:
                report.warnings.append(
                    f"Opening Balances: rider_id '{rid}' ambiguous - needs company"
                )
            pr = rows[0] if len(rows) == 1 else None
        if not pr:
            report.warnings.append(f"Opening Balances: rider '{rid}' not found")
            unresolved += 1
            continue
        person_id = pr["person_id"]
        if person_id in seen:
            report.warnings.append(
                f"Opening Balances: person for '{rid}' listed twice - extra skipped"
            )
            skipped += 1
            continue
        seen.add(person_id)
        if conn.execute(
            "SELECT 1 FROM transactions WHERE person_id=? AND event_type='OPENING'", (person_id,)
        ).fetchone():
            skipped += 1
            continue
        dues = to_paise(to_float(_cell(row, c["dues"])) or 0)
        arr = to_paise(to_float(_cell(row, c["arr"])) or 0)
        cod = to_paise(to_float(_cell(row, c["cod"])) or 0) if c.get("cod") else 0
        if dues == 0 and arr == 0 and cod == 0:
            continue
        final_bal = -abs(dues)
        if dues:
            conn.execute(
                "INSERT INTO balances (person_id, current_balance, last_updated) VALUES (?,?,?) "
                "ON CONFLICT(person_id) DO UPDATE SET current_balance=excluded.current_balance, "
                "last_updated=excluded.last_updated",
                (person_id, final_bal, today),
            )
            conn.execute(
                "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, event_type, amount, balance_after, remarks, created_by) VALUES (?,?,?,?,?,'OPENING',?,?,?,?)",  # noqa: E501
                (
                    person_id,
                    rid,
                    co or "",
                    today,
                    today,
                    final_bal,
                    final_bal,
                    "Opening dues",
                    created_by,
                ),
            )
        if arr:
            a = abs(arr)
            conn.execute(
                "INSERT INTO ev_arrears (person_id, total_missed, outstanding, last_updated) "
                "VALUES (?,?,?,?) ON CONFLICT(person_id) DO UPDATE SET "
                "total_missed=excluded.total_missed, outstanding=excluded.outstanding, "
                "last_updated=excluded.last_updated",
                (person_id, a, a, today),
            )
            conn.execute(
                "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, event_type, amount, balance_after, remarks, created_by) VALUES (?,?,?,?,?,'OPENING',?,?,?,?)",  # noqa: E501
                (
                    person_id,
                    rid,
                    co or "",
                    today,
                    today,
                    -a,
                    final_bal,
                    "Opening EV arrears",
                    created_by,
                ),
            )
        if cod:
            c_abs = abs(cod)
            conn.execute(
                "INSERT INTO ev_arrears (person_id, cod_missed, cod_outstanding, last_updated) "
                "VALUES (?,?,?,?) ON CONFLICT(person_id) DO UPDATE SET "
                "cod_missed=excluded.cod_missed, cod_outstanding=excluded.cod_outstanding, "
                "last_updated=excluded.last_updated",
                (person_id, c_abs, c_abs, today),
            )
            conn.execute(
                "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
                "event_type, amount, balance_after, remarks, created_by) "
                "VALUES (?,?,?,?,?,'OPENING',?,?,?,?)",
                (
                    person_id,
                    rid,
                    co or "",
                    today,
                    today,
                    -c_abs,
                    final_bal,
                    "Opening COD pending",
                    created_by,
                ),
            )
        applied += 1
    report.stats["balances"] = {"applied": applied, "skipped": skipped, "unresolved": unresolved}


def _process_seed(workbook_bytes, commit, created_by):
    report = SeedReport(committed=commit)
    xl = pd.ExcelFile(BytesIO(workbook_bytes))
    conn = get_connection()
    try:
        _import_roster(conn, xl, report)
        _import_ev(conn, xl, report)
        _import_balances(conn, xl, report, created_by)
        if commit and not report.errors:
            conn.commit()
        else:
            # Dry run, or a sheet failed validation: a half-imported seed (roster
            # rejected, EVs and balances still written) used to be committed.
            conn.rollback()
            report.committed = False
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return report


def preview_seed(workbook_bytes):
    return _process_seed(workbook_bytes, commit=False, created_by="seed_preview")


def import_seed(workbook_bytes, created_by="seed_import"):
    return _process_seed(workbook_bytes, commit=True, created_by=created_by)
