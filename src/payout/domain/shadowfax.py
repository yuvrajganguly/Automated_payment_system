"""Shadowfax — many cumulative daily files in, one per-order cycle out.

Shadowfax sends one ``Vendor_data_<download date>.xlsx`` a day, and each file
repeats every earlier order date of the month, *revised*: a day's count can go
up in a later file. So the files are never added up. For each (rider, order
date, pincode) the row from the newest file wins, newest by the date in the
file name, falling back to the file's latest order date.

A rider is paid from our pincode ratecard (``company_pincode_rates``), never
from Shadowfax's ``Total_Payout``, which is what they pay *us* and is kept
only for the margin column:

    ppd × PPD + cod × COD + rev × RVP + sdd × SDD + clubbed × Club

A pincode with no rate falls back to the company's ``per_order_rate`` for
ppd+cod+rev+sdd plus the card's usual Club rate, and is flagged. FM, RTS and
large-shipment orders have no rate: paid ₹0 and flagged, never refused.

The output is a ``ParseResult`` with each rider's gross as ``payout`` (paise),
exactly what a client file produces, so the cycle — rent, arrears, dues,
holds, the workbook — runs unchanged. The rider's hub is *not* passed on: the
engine would rewrite ``rider_master.hub`` from it, and Shadowfax's hub names
are not ours. It is kept in the detail for display and for onboarding.

Days a committed cycle already paid (``payout_order_days``) are left out and
listed; a day revised after it was paid is reported, not re-paid.
"""

from __future__ import annotations

import io
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date

import pandas as pd

from payout.domain.models import ParseResult, RiderRecord

RATE_MODEL = "pincode_ratecard"
_NAME_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
# (count column in the file, rate column in the card, our key)
_TYPES = (
    ("fwd_ppd_orders", "ppd", "ppd"),
    ("fwd_cod_orders", "cod", "cod"),
    ("rev_orders", "rvp", "rvp"),
    ("sdd_orders", "sdd", "sdd"),
    ("clubbed_orders", "club", "club"),
)
_UNRATED = (("fm_orders", "fm"), ("rts_orders", "rts"), ("Large_shipment", "large"))


def norm_hub(s) -> str:
    """'CCU_Narendrapur' and 'Narendra Pur' are the same store."""
    s = str(s or "").strip()
    if s.lower() in ("", "nan", "none"):
        return ""
    s = re.sub(r"^ccu[_\s-]*", "", s, flags=re.I)
    return re.sub(r"[\s_\-]+", "", s).lower()


def _rid(v) -> str:
    s = str(v).strip()
    return s[:-2] if s.endswith(".0") else s


def _int(v) -> int:
    try:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return 0
        return int(round(float(v)))
    except (TypeError, ValueError):
        return 0


@dataclass
class SourceFile:
    name: str
    file_date: str
    rows: int
    order_dates: list[str]
    dated_by: str  # "name" | "content"


@dataclass
class Batch:
    files: list[SourceFile] = field(default_factory=list)
    rows: dict = field(default_factory=dict)  # (rid, od, pin) -> row dict incl. _file
    date_source: dict = field(default_factory=dict)  # order_date -> file name
    ztp: dict = field(default_factory=dict)  # awb -> row
    warnings: list[str] = field(default_factory=list)


def read_files(files: list[tuple[str, bytes]]) -> Batch:
    """Read every file's ``Vendor_data`` (and ``ZTP Deductions``), newest file
    wins per (rider_id, order_date, pincode)."""
    b = Batch()
    loaded = []
    for name, data in files:
        try:
            xl = pd.ExcelFile(io.BytesIO(data))
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"{name}: not a readable .xlsx ({e})") from e
        if "Vendor_data" not in xl.sheet_names:
            raise ValueError(f"{name}: no 'Vendor_data' sheet — is this a Shadowfax download?")
        vd = pd.read_excel(xl, sheet_name="Vendor_data")
        if "rider_id" not in vd.columns or "order_date" not in vd.columns:
            raise ValueError(f"{name}: Vendor_data has no rider_id / order_date columns")
        vd = vd[vd["rider_id"].notna()].copy()
        vd["order_date"] = pd.to_datetime(vd["order_date"], errors="coerce").dt.date
        vd = vd[vd["order_date"].notna()]
        ods = sorted({d.isoformat() for d in vd["order_date"]})
        m = _NAME_DATE.search(name or "")
        if m:
            fdate, by = m.group(1), "name"
        elif ods:
            fdate, by = ods[-1], "content"
        else:
            fdate, by = "0000-00-00", "content"
        ztp = (
            pd.read_excel(xl, sheet_name="ZTP Deductions")
            if "ZTP Deductions" in xl.sheet_names
            else None
        )
        loaded.append((fdate, name, vd, ztp, ods, by))
    # oldest first, so a newer file overwrites; ties keep upload order
    loaded.sort(key=lambda x: x[0])
    for fdate, name, vd, ztp, ods, by in loaded:
        b.files.append(
            SourceFile(name=name, file_date=fdate, rows=len(vd), order_dates=ods, dated_by=by)
        )
        for _, r in vd.iterrows():
            od = r["order_date"].isoformat()
            key = (_rid(r["rider_id"]), od, _rid(r.get("pincode", "")))
            row = {c: r[c] for c in vd.columns}
            row["_file"], row["_file_date"], row["order_date"] = name, fdate, od
            b.rows[key] = row
            b.date_source[od] = name
        if ztp is not None and len(ztp):
            for _, z in ztp.iterrows():
                awb = str(z.get("awb_number", "")).strip()
                if awb and awb.lower() != "nan":
                    b.ztp[awb] = {
                        "rider_id": _rid(z.get("rider_id")),
                        "awb_number": awb,
                        "fraud_type": str(z.get("fraud_type") or ""),
                        "penalty": round(float(z.get("total_penalty_amount") or 0) * 100),
                        "created_date": str(z.get("created_date") or "")[:10],
                    }
    return b


def load_rates(conn, company: str) -> dict[str, list[dict]]:
    """pincode -> rate rows (paise), newest effective_from first."""
    out: dict[str, list[dict]] = defaultdict(list)
    for r in conn.execute(
        "SELECT pincode, cluster, rvp, cod, ppd, sdd, club, effective_from "
        "FROM company_pincode_rates WHERE company=? ORDER BY effective_from DESC",
        (company,),
    ).fetchall():
        out[str(r["pincode"])].append(dict(r))
    return out


def _rate_for(rates, pin: str, od: str):
    for r in rates.get(pin, []):
        if str(r["effective_from"])[:10] <= od:
            return r
    return None


def paid_days(conn, company: str) -> dict[tuple[str, str], dict]:
    return {
        (r["rider_id"], r["order_date"]): dict(r)
        for r in conn.execute(
            "SELECT rider_id, order_date, orders, gross, cycle_start, cycle_end "
            "FROM payout_order_days WHERE company=?",
            (company,),
        ).fetchall()
    }


@dataclass
class Priced:
    records: list[RiderRecord]
    riders: list[dict]
    detail: list[dict]
    already_paid: list[dict]
    revised: list[dict]
    ztp: list[dict]
    order_dates: list[dict]
    ratecard_used: list[dict]
    warnings: list[str]
    totals: dict
    day_rows: list[dict]  # (rider, order_date, orders, gross) to record on commit


def price(
    conn,
    company: str,
    batch: Batch,
    cycle_start: date,
    cycle_end: date,
    *,
    fallback_rate: int | None,
) -> Priced:
    rates = load_rates(conn, company)
    club_default = Counter(r["club"] for rs in rates.values() for r in rs).most_common(1)
    club_fallback = club_default[0][0] if club_default else 700
    paid = paid_days(conn, company)
    cs, ce = cycle_start.isoformat(), cycle_end.isoformat()

    detail: list[dict] = []
    already: dict[tuple[str, str], dict] = {}
    revised_map: dict[tuple[str, str], dict] = {}
    used_pins: dict[str, dict] = {}
    per_day: dict[tuple[str, str], dict] = defaultdict(lambda: {"orders": 0, "gross": 0})
    warnings: list[str] = list(batch.warnings)

    for (rid, od, pin), r in sorted(batch.rows.items()):
        if not (cs <= od <= ce):
            continue
        counts = {k: _int(r.get(col)) for col, _, k in _TYPES}
        unrated = {k: _int(r.get(col)) for col, k in _UNRATED}
        total = sum(counts.values()) + unrated["fm"] + unrated["rts"]
        flags = []
        rate = _rate_for(rates, pin, od)
        if rate is not None:
            used_pins[pin] = rate
            pay = sum(counts[k] * int(rate[rk]) for _, rk, k in _TYPES)
            rates_used = {f"rate_{k}": int(rate[rk]) for _, rk, k in _TYPES}
        else:
            if not fallback_rate:
                raise ValueError(
                    f"Pincode {pin} has no rate and {company} has no per-order rate to fall back on"
                )
            base = counts["ppd"] + counts["cod"] + counts["rvp"] + counts["sdd"]
            pay = base * int(fallback_rate) + counts["club"] * club_fallback
            rates_used = {
                "rate_ppd": int(fallback_rate),
                "rate_cod": int(fallback_rate),
                "rate_rvp": int(fallback_rate),
                "rate_sdd": int(fallback_rate),
                "rate_club": club_fallback,
            }
            if total:
                flags.append("rate fallback")
        if any(unrated.values()):
            flags.append(
                "unrated: " + ", ".join(f"{v} {k}" for k, v in unrated.items() if v) + " paid ₹0"
            )
        sfx = round(float(r.get("Total_Payout") or 0) * 100)
        line = {
            "rider_id": rid,
            "name": str(r.get("rider_name") or "").strip(),
            "file_hub": "" if norm_hub(r.get("hub")) == "" else str(r.get("hub")).strip(),
            "order_date": od,
            "pincode": pin,
            "cluster": (rate or {}).get("cluster") or str(r.get("pincode_category") or ""),
            **{f"{k}_orders": v for k, v in counts.items()},
            **{f"{k}_orders": v for k, v in unrated.items()},
            "orders": total,
            **rates_used,
            "rider_pay": pay,
            "sfx_payout": sfx,
            "margin": sfx - pay,
            "flags": flags,
            "source_file": r["_file"],
        }
        prior = paid.get((rid, od))
        if prior and not (prior["cycle_start"] == cs and prior["cycle_end"] == ce):
            a = already.setdefault(
                (rid, od),
                {
                    "rider_id": rid,
                    "name": line["name"],
                    "order_date": od,
                    "orders": 0,
                    "gross": 0,
                    "cycle": f"{prior['cycle_start']}..{prior['cycle_end']}",
                    "paid_orders": int(prior["orders"]),
                    "paid_gross": int(prior["gross"]),
                },
            )
            a["orders"] += total
            a["gross"] += pay
            continue
        detail.append(line)
        per_day[(rid, od)]["orders"] += total
        per_day[(rid, od)]["gross"] += pay

    for a in already.values():
        d_orders, d_gross = a["orders"] - a["paid_orders"], a["gross"] - a["paid_gross"]
        if d_orders or d_gross:
            revised_map[(a["rider_id"], a["order_date"])] = {
                "rider_id": a["rider_id"],
                "name": a["name"],
                "order_date": a["order_date"],
                "cycle": a["cycle"],
                "orders_delta": d_orders,
                "revised_pay": d_gross,
            }

    # ── per rider ────────────────────────────────────────────────────────────
    by: dict[str, dict] = {}
    for line in detail:
        r = by.setdefault(
            line["rider_id"],
            {
                "rider_id": line["rider_id"],
                "name": line["name"],
                "file_hub": line["file_hub"],
                "days": set(),
                "orders": 0,
                **{f"{k}_orders": 0 for _, _, k in _TYPES},
                **{f"{k}_orders": 0 for _, k in _UNRATED},
                "gross": 0,
                "sfx_payout": 0,
                "flags": set(),
            },
        )
        if not r["file_hub"] and line["file_hub"]:
            r["file_hub"] = line["file_hub"]
        for _, _, k in _TYPES:
            r[f"{k}_orders"] += line[f"{k}_orders"]
        for _, k in _UNRATED:
            r[f"{k}_orders"] += line[f"{k}_orders"]
        r["orders"] += line["orders"]
        r["gross"] += line["rider_pay"]
        r["sfx_payout"] += line["sfx_payout"]
        if line["orders"] > 0:
            r["days"].add(line["order_date"])
        r["flags"].update(line["flags"])

    ztp_rows = []
    for z in batch.ztp.values():
        ztp_rows.append({**z, "name": by.get(z["rider_id"], {}).get("name", "")})

    riders, records = [], []
    for rid, r in sorted(by.items(), key=lambda kv: kv[1]["name"].lower()):
        out = {
            **r,
            "days": len(r["days"]),
            "flags": sorted(r["flags"]),
            "margin": r["sfx_payout"] - r["gross"],
            "ztp_penalty": sum(z["penalty"] for z in ztp_rows if z["rider_id"] == rid),
        }
        riders.append(out)
        if r["orders"] <= 0:
            continue  # a zero-order row is not an error, and not a payout
        # hub deliberately None: the engine would overwrite rider_master.hub
        records.append(
            RiderRecord(rider_id=rid, payout=r["gross"], orders=float(r["orders"]), name=r["name"])
        )

    # ── dates: found vs the cycle ────────────────────────────────────────────
    found = sorted({od for (_, od, _) in batch.rows if cs <= od <= ce})
    days = []
    d = cycle_start
    while d <= cycle_end:
        iso = d.isoformat()
        days.append(
            {"order_date": iso, "found": iso in found, "source_file": batch.date_source.get(iso)}
        )
        d = date.fromordinal(d.toordinal() + 1)
    missing = [str(x["order_date"]) for x in days if not x["found"]]
    if missing:
        warnings.append(
            "No Shadowfax data for "
            + ", ".join(missing)
            + " — a day nobody worked, or a file not uploaded."
        )
    if already:
        warnings.append(
            f"{len(already)} rider-day(s) were already paid in an earlier cycle and are left out."
        )
    fallback_n = sum(1 for x in detail if "rate fallback" in x["flags"])
    if fallback_n:
        pins = sorted({x["pincode"] for x in detail if "rate fallback" in x["flags"]})
        warnings.append(
            f"{fallback_n} row(s) at pincodes with no rate ({', '.join(pins)}) paid at the fallback rate."  # noqa: E501
        )
    if any(x["flags"] and any(f.startswith("unrated") for f in x["flags"]) for x in detail):
        warnings.append(
            "Some rows carry FM / RTS / large-shipment orders, which have no rate and were paid ₹0."
        )

    totals = {
        "orders": sum(r["orders"] for r in riders),
        "gross": sum(r["gross"] for r in riders),
        "sfx_payout": sum(r["sfx_payout"] for r in riders),
        **{f"{k}_orders": sum(r[f"{k}_orders"] for r in riders) for _, _, k in _TYPES},
    }
    totals["margin"] = totals["sfx_payout"] - totals["gross"]
    ratecard_used = [
        {
            "pincode": p,
            "cluster": r["cluster"],
            "effective_from": str(r["effective_from"])[:10],
            **{f"rate_{k}": int(r[rk]) for _, rk, k in _TYPES},
        }
        for p, r in sorted(used_pins.items())
    ]
    day_rows = [
        {"rider_id": rid, "order_date": od, "orders": v["orders"], "gross": v["gross"]}
        for (rid, od), v in sorted(per_day.items())
    ]
    return Priced(
        records=records,
        riders=riders,
        detail=detail,
        already_paid=list(already.values()),
        revised=list(revised_map.values()),
        ztp=ztp_rows,
        order_dates=days,
        ratecard_used=ratecard_used,
        warnings=warnings,
        totals=totals,
        day_rows=day_rows,
    )


def to_parse_result(company: str, priced: Priced) -> ParseResult:
    res = ParseResult(company=company, records=list(priced.records), sheet="Vendor_data")
    res.warnings.extend(priced.warnings)
    return res


def record_paid_days(
    conn, company: str, cycle_start: date, cycle_end: date, day_rows: list[dict]
) -> None:
    """On commit: this cycle paid these (rider, order_date) days. A forced
    re-run of the same cycle replaces its own rows."""
    cs, ce = cycle_start.isoformat(), cycle_end.isoformat()
    conn.execute(
        "DELETE FROM payout_order_days WHERE company=? AND cycle_start=? AND cycle_end=?",
        (company, cs, ce),
    )
    for d in day_rows:
        conn.execute(
            "INSERT INTO payout_order_days (company, rider_id, order_date, orders, gross, "
            "cycle_start, cycle_end) VALUES (?,?,?,?,?,?,?)",
            (company, d["rider_id"], d["order_date"], d["orders"], d["gross"], cs, ce),
        )


def suggest_cycle(batch: Batch, last_cycle_end: str | None) -> tuple[str | None, str | None]:
    """Earliest and latest order date across the files, clamped to after the
    last committed cycle."""
    ods = sorted({od for (_, od, _) in batch.rows})
    if not ods:
        return None, None
    start, end = ods[0], ods[-1]
    if last_cycle_end and start <= last_cycle_end:
        start = date.fromordinal(
            date.fromisoformat(last_cycle_end[:10]).toordinal() + 1
        ).isoformat()
    if start > end:
        return None, None
    return start, end
