"""Zomato — daily FE reports in, one cycle out, three kinds of rider id.

Zomato sends one report per vendor per day: the vendor name and the date sit
in two cells at the top ("Select Vendor Name", "Select Date" → 20261127) and
the riders in a table under a header row that starts "FE ID | FE Name |
Total Orders | Rain Orders | … | Total Login Hours | …".

Qwikserve has two Zomato vendor codes, and the ids under them are paid three
ways (``rider_master.payment_model`` on each id):

* **Flat** (``per_order``) — ZFPP vendor. We pay orders × the per-order rate
  (the rider's store's if set, else Zomato's under Admin → Companies).
* **Salary** (``salary``) — also ZFPP. Same report; we pay the rider's salary
  less a day's pay per day short of the expected days, plus the incentives,
  exactly as for any salaried company. A day counts as present when the
  rider logged in or delivered that day.
* **Commission** (``commission``) — MFFLEET vendor. Zomato pays these riders
  itself and pays Qwikserve a commission. Nothing is paid out here; their
  orders and hours are listed (COMMISSION sheet) so the commission can be
  checked, and their EV rent is collected the cash way, like any direct-pay
  rider.

An id whose type is not set yet is taken from its vendor: MFFLEET means
Commission. A ZFPP id with no type cannot be guessed — Flat and Salary pay
very different money — so it is left out of the pay and listed for the office
to set. A rider not on the roster at all goes through the usual onboarding
prompt, priced at the flat rate meanwhile.

Each (rider, day) is paid once: days a committed cycle already paid
(``payout_order_days``) are skipped, as for Shadowfax. If the same day comes
in twice (a re-download), the later file wins.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from payout.domain.models import ParseResult, RiderRecord

PARSER_TYPE = "zomato"
COMMISSION_VENDORS = ("MFFLEET",)
_DATE8 = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})")

# Column → our key. Matched case- and space-insensitively.
_COLS = {
    "feid": "fe_id",
    "fename": "fe_name",
    "totalorders": "orders",
    "rainorders": "rain_orders",
    "batchedorders": "batched_orders",
    "peakloginhoursorders": "peak_orders",
    "totalloginhours": "login_hours",
    "totalpeakloginhours": "peak_login_hours",
    "totalcancellations": "cancellations",
    "totaldenials": "denials",
    "totalpostacceptancedenials": "post_acceptance_denials",
}
_NUMERIC = (
    "orders",
    "rain_orders",
    "batched_orders",
    "peak_orders",
    "login_hours",
    "peak_login_hours",
    "cancellations",
    "denials",
    "post_acceptance_denials",
)


def _key(v) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v or "").lower())


def _num(v) -> float:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0.0
        return float(str(v).replace(",", "").strip() or 0)
    except (TypeError, ValueError):
        return 0.0


def _fe(v) -> str:
    s = str(v if v is not None else "").strip()
    if s.lower() in ("", "nan", "none"):
        return ""
    return s[:-2] if s.endswith(".0") and s[:-2].isdigit() else s


def _parse_day(v) -> str | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if hasattr(v, "date") and not isinstance(v, str):
        try:
            return v.date().isoformat()
        except (AttributeError, ValueError):
            pass
    m = _DATE8.search(_fe(v))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
    except ValueError:
        return None


def vendor_kind(vendor: str) -> str:
    """'commission' for an MFFLEET report, 'zfpp' for everything else."""
    v = (vendor or "").upper()
    return "commission" if any(c in v for c in COMMISSION_VENDORS) else "zfpp"


@dataclass
class DayFile:
    name: str
    vendor: str
    day: str
    rows: int


@dataclass
class Batch:
    files: list[DayFile] = field(default_factory=list)
    # (fe_id, day) -> row dict (numeric fields + fe_name + vendor + _file)
    rows: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _label_value(grid: list[list], label: str):
    """The first non-empty cell to the right of (or under) a label cell."""
    want = _key(label)
    for i, row in enumerate(grid):
        for j, cell in enumerate(row):
            if _key(cell) == want:
                for k in range(j + 1, len(row)):
                    if _fe(row[k]):
                        return row[k]
                if i + 1 < len(grid) and j < len(grid[i + 1]) and _fe(grid[i + 1][j]):
                    return grid[i + 1][j]
    return None


def read_sheet(name: str, grid: list[list]) -> tuple[str, str, list[dict]]:
    """(vendor, day, rows) from one sheet given as a list of rows of cells."""
    head_at = next(
        (i for i, row in enumerate(grid) if any(_key(c) == "feid" for c in row)),
        None,
    )
    if head_at is None:
        raise ValueError(f"{name}: no 'FE ID' header row — is this a Zomato FE report?")
    header = grid[head_at]
    cols = {j: _COLS[_key(c)] for j, c in enumerate(header) if _key(c) in _COLS}
    if "orders" not in cols.values():
        raise ValueError(f"{name}: no 'Total Orders' column next to FE ID")
    vendor = str(_label_value(grid[:head_at], "Select Vendor Name") or "").strip()
    day = _parse_day(_label_value(grid[:head_at], "Select Date")) or _parse_day(name)
    if not day:
        raise ValueError(f"{name}: no date — neither a 'Select Date' cell nor a date in the name")
    out = []
    for row in grid[head_at + 1 :]:
        rec = {key: (row[j] if j < len(row) else None) for j, key in cols.items()}
        fe = _fe(rec.get("fe_id"))
        if not fe:
            continue
        for k in _NUMERIC:
            rec[k] = _num(rec.get(k))
        rec["fe_id"] = fe
        rec["fe_name"] = _fe(rec.get("fe_name"))
        out.append(rec)
    return vendor, day, out


def read_files(files: list[tuple[str, bytes]]) -> Batch:
    """Every sheet of every file that carries an FE table. A later file wins
    for the same (FE ID, day)."""
    b = Batch()
    for name, data in files:
        try:
            xl = pd.ExcelFile(io.BytesIO(data))
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"{name}: not a readable .xlsx ({e})") from e
        found = False
        for sheet in xl.sheet_names:
            df = pd.read_excel(xl, sheet_name=sheet, header=None, dtype=object)
            grid = df.where(pd.notna(df), None).values.tolist()
            if not any(_key(c) == "feid" for row in grid for c in row):
                continue
            vendor, day, rows = read_sheet(f"{name} [{sheet}]", grid)
            found = True
            b.files.append(DayFile(name=name, vendor=vendor, day=day, rows=len(rows)))
            for r in rows:
                r["vendor"], r["_file"], r["day"] = vendor, name, day
                b.rows[(r["fe_id"], day)] = r
        if not found:
            raise ValueError(f"{name}: no sheet with an 'FE ID' table")
    return b


@dataclass
class Priced:
    records: list[RiderRecord] = field(default_factory=list)
    riders: list[dict] = field(default_factory=list)  # one per FE ID, every kind
    commission: list[dict] = field(default_factory=list)
    needs_type: list[dict] = field(default_factory=list)
    already_paid: list[dict] = field(default_factory=list)
    day_rows: list[dict] = field(default_factory=list)  # to record on commit
    warnings: list[str] = field(default_factory=list)


def price(conn, company: str, batch: Batch, cycle_start: date, cycle_end: date, co) -> Priced:
    """Route every FE ID by its type and price the paid ones.

    ``co`` is the company row (per_order_rate, salary_expected_days,
    incentive_per_order, incentive_per_day), all money in paise."""
    from payout.domain.payment_model import rider_payment_model

    cs, ce = cycle_start.isoformat(), cycle_end.isoformat()
    p = Priced()
    paid = {
        (r["rider_id"], r["order_date"]): r["cycle_start"] + " → " + r["cycle_end"]
        for r in conn.execute(
            "SELECT rider_id, order_date, cycle_start, cycle_end FROM payout_order_days "
            "WHERE company=?",
            (company,),
        ).fetchall()
    }
    roster = {
        r["rider_id"]: r
        for r in conn.execute(
            "SELECT rm.rider_id, rm.name, rm.salary, rm.hub, rm.payment_model, "
            "       c.payment_model AS company_model "
            "FROM rider_master rm LEFT JOIN companies c ON c.company_name = rm.company "
            "WHERE rm.company=?",
            (company,),
        ).fetchall()
    }
    store = {
        r["rider_id"]: r
        for r in conn.execute(
            "SELECT rm.rider_id, ch.per_order_rate, ch.salary, ch.incentive_per_order, "
            "       ch.incentive_per_day "
            "FROM rider_master rm JOIN company_hubs ch ON ch.company=rm.company AND ch.hub=rm.hub "
            "WHERE rm.company=?",
            (company,),
        ).fetchall()
    }
    flat_rate = int(co["per_order_rate"] or 0)
    expected = int(co["salary_expected_days"] or 26)

    # Gather each FE ID's days inside the cycle.
    per: dict[str, dict] = {}
    for (fe, day), r in sorted(batch.rows.items(), key=lambda kv: kv[0][1]):
        if not (cs <= day <= ce):
            continue
        if (fe, day) in paid:
            p.already_paid.append(
                {"rider_id": fe, "day": day, "cycle": paid[(fe, day)], "orders": r["orders"]}
            )
            continue
        x = per.setdefault(
            fe,
            {
                "rider_id": fe,
                "file_name": r["fe_name"],
                "vendors": set(),
                "days": [],
                "orders": 0.0,
                "rain_orders": 0.0,
                "login_hours": 0.0,
                "days_present": 0,
                "cancellations": 0.0,
                "denials": 0.0,
            },
        )
        x["vendors"].add(r["vendor"])
        x["days"].append((day, r["orders"]))
        for k in ("orders", "rain_orders", "login_hours", "cancellations", "denials"):
            x[k] += r[k]
        if r["orders"] > 0 or r["login_hours"] > 0:
            x["days_present"] += 1

    for fe, x in sorted(per.items()):
        vendor_says = (
            "commission" if all(vendor_kind(v) == "commission" for v in x["vendors"]) else "zfpp"
        )
        known = roster.get(fe)
        if known is not None:
            own = known["payment_model"]
            model = own or (
                "commission" if vendor_says == "commission" else rider_payment_model(known)
            )
        else:
            model = "commission" if vendor_says == "commission" else "per_order"
        name = (known["name"] if known is not None else None) or x["file_name"]
        line = {
            "rider_id": fe,
            "name": name,
            "known": known is not None,
            "vendor": ", ".join(sorted(v for v in x["vendors"] if v)),
            "days_present": x["days_present"],
            "orders": x["orders"],
            "rain_orders": x["rain_orders"],
            "login_hours": round(x["login_hours"], 2),
            "cancellations": x["cancellations"],
            "denials": x["denials"],
            "type": {"per_order": "Flat", "salary": "Salary", "commission": "Commission"}.get(
                model, model
            ),
            "gross": 0,
            "working": "",
        }
        if model in ("commission", "direct"):
            line["type"] = "Commission"
            if vendor_says == "zfpp" and known is not None and not known["payment_model"]:
                # On the ZFPP report but nobody said Flat or Salary.
                line["type"] = "Not set"
                p.needs_type.append(line)
            else:
                if vendor_says == "zfpp":
                    p.warnings.append(
                        f"{name} ({fe}) is set as Commission but is on the ZFPP report — not paid"
                    )
                p.commission.append(line)
            p.riders.append(line)
            continue
        st = store.get(fe)
        if model == "salary":
            salary = int((known["salary"] if known is not None else 0) or 0) or int(
                (st["salary"] if st is not None else 0) or 0
            )
            if not salary:
                p.warnings.append(
                    f"{name} ({fe}) is a Salary id with no salary set — paid ₹0; set it on "
                    "the rider page or as the store default"
                )
            inc_o = int(
                st["incentive_per_order"]
                if st is not None and st["incentive_per_order"] is not None
                else co["incentive_per_order"] or 0
            )
            inc_d = int(
                st["incentive_per_day"]
                if st is not None and st["incentive_per_day"] is not None
                else co["incentive_per_day"] or 0
            )
            days_off = max(0, expected - x["days_present"])
            base = max(0, int(round(salary - days_off * salary / expected))) if salary else 0
            inc = int(round(x["orders"] * inc_o + x["days_present"] * inc_d))
            gross = base + inc
            line["working"] = (
                f"salary ₹{salary / 100:,.0f} − {days_off} day(s) off"
                f" + ₹{inc / 100:,.0f} incentives"
            )
        else:  # per_order — Flat (also any other model on the ZFPP report)
            rate = int((st["per_order_rate"] if st is not None else None) or flat_rate)
            if not rate:
                raise ValueError(
                    f"{company} has no per-order rate for Flat ids — set it under "
                    "Admin → Companies (or the rider's store)."
                )
            gross = int(round(x["orders"] * rate))
            line["working"] = f"{x['orders']:g} orders × ₹{rate / 100:g}"
            line["type"] = "Flat"
            if known is None:
                line["working"] += " (not on the roster yet — flat rate until onboarded)"
        line["gross"] = gross
        p.riders.append(line)
        p.records.append(
            RiderRecord(rider_id=fe, payout=gross, orders=x["orders"], name=x["file_name"] or None)
        )
        # Spread the gross over the days so a later revision can be traced.
        total_orders = sum(o for _, o in x["days"]) or 0
        for day, o in x["days"]:
            share = int(round(gross * (o / total_orders))) if total_orders else 0
            p.day_rows.append({"rider_id": fe, "order_date": day, "orders": int(o), "gross": share})

    if p.needs_type:
        names = ", ".join(f"{r['name']} ({r['rider_id']})" for r in p.needs_type[:8])
        more = len(p.needs_type) - 8
        p.warnings.append(
            f"{len(p.needs_type)} Zomato id(s) on the ZFPP report have no type — set Flat or "
            f"Salary on the rider page, then preview again: {names}"
            + (f" … +{more} more" if more > 0 else "")
        )
    if p.already_paid:
        p.warnings.append(
            f"{len(p.already_paid)} rider-day(s) were already paid by an earlier cycle and are "
            "left out"
        )
    return p


def to_parse_result(company: str, priced: Priced) -> ParseResult:
    res = ParseResult(company=company, records=list(priced.records), sheet="Zomato FE report")
    res.matched_columns = {
        "rider_id": "FE ID",
        "payout": "Flat: orders × rate · Salary: salary − days off + incentives",
        "orders": "Total Orders",
    }
    res.warnings.extend(priced.warnings)
    return res
