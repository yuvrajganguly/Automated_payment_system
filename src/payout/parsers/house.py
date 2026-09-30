"""The house sheet — our own payout layout for a company that sends no file.

Some clients never send a payout file; the office computes what each rider
earned from the client's portal and pays them itself. Until now those weeks
went into the ledger by hand, one rider at a time, or not at all. This
parser takes the office's own four columns — **Person ID · Gross payout ·
Rent charged · Net payout** — and turns them into the same ``ParseResult``
a client file produces, so the cycle runs exactly as it does for Jiffy or
Myntra: PAYOUT for the gross, rent from the assignments, arrears recovered,
dues carried, the bank file at the end.

Two rules the layout is built around:

* **Keyed on Person ID**, because the office knows people, not the ids a
  client hands out; the parser resolves each person to their active rider
  id at this company and refuses a row it cannot place. A ``Rider ID``
  column, if present, wins over the lookup.
* **Rent charged and Net payout are checked, never obeyed.** The engine
  computes rent from the vehicle's days; a sheet that says ₹1,110 where the
  engine says ₹1,295 is shown side by side in the preview before anything
  commits. The ledger's rent is always computed.

Selected with ``companies.parser_type = 'house'``.
"""

from __future__ import annotations

import io
import re
import sqlite3

import pandas as pd

from payout.domain.models import ParseResult, RiderRecord
from payout.money import to_paise

PARSER_TYPE = "house"

_ALIASES: dict[str, tuple[str, ...]] = {
    "person_id": ("person id", "person", "pid", "person_id", "personid", "person no"),
    "rider_id": ("rider id", "rider_id", "riderid", "id at company", "company id"),
    "name": ("name", "rider", "rider name", "worker name"),
    "gross": (
        "gross payout",
        "gross",
        "payout",
        "gross pay",
        "earnings",
        "earning",
        "amount",
        "total payable",
    ),
    "rent": ("rent charged", "rent", "ev rent", "rent deducted"),
    "net": ("net payout", "net", "net pay", "payable", "net payable", "to pay"),
}
_REQUIRED = ("person_id", "gross")
_HEADER_WORDS = {w for ws in _ALIASES.values() for w in ws}


def _norm(s) -> str:
    return re.sub(r"[\s_]+", " ", str(s or "").strip().lower())


def _with_header_row(raw: pd.DataFrame) -> pd.DataFrame:
    best, best_hits = 0, 0
    for i in range(min(15, len(raw))):
        cells = [_norm(v) for v in raw.iloc[i].tolist() if str(v).strip() and str(v) != "nan"]
        hits = sum(1 for c in cells if c in _HEADER_WORDS)
        if hits > best_hits:
            best, best_hits = i, hits
    header = [str(v).strip() for v in raw.iloc[best].tolist()]
    header = [h if h and h.lower() != "nan" else f"col_{n}" for n, h in enumerate(header)]
    out = raw.iloc[best + 1 :].copy()
    out.columns = header
    return out.reset_index(drop=True)


def _match_columns(df: pd.DataFrame) -> dict[str, str]:
    found: dict[str, str] = {}
    cols = {_norm(c): c for c in df.columns}
    for logical, names in _ALIASES.items():
        for n in names:
            if n in cols:
                found[logical] = cols[n]
                break
    return found


def _read(file_bytes: bytes) -> pd.DataFrame:
    try:
        return pd.read_excel(io.BytesIO(file_bytes), header=None)
    except Exception:  # noqa: BLE001 — not an xlsx; try csv
        return pd.read_csv(io.BytesIO(file_bytes), header=None)


def _money(v) -> int | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    s = str(v).replace(",", "").replace("₹", "").strip()
    if not s or s.lower() in ("nan", "none", "-", "–"):
        return None
    return to_paise(s)


def _resolve_rider_ids(company: str, person_ids: list[int]) -> dict[int, str]:
    """person_id → the active rider id at ``company`` (the person's deduction
    anchor if it is at this company, else the first active id here)."""
    from payout.db import get_connection

    if not person_ids:
        return {}
    out: dict[int, str] = {}
    with get_connection() as conn:
        marks = ",".join("?" * len(person_ids))
        rows = conn.execute(
            f"SELECT rm.person_id, rm.rider_id, "
            f"       CASE WHEN rm.rider_id = pr.deduction_rider_id THEN 0 ELSE 1 END AS rank "
            f"FROM rider_master rm JOIN person_registry pr ON pr.person_id = rm.person_id "
            f"WHERE rm.company = ? AND COALESCE(rm.is_active, 1) = 1 "
            f"  AND rm.person_id IN ({marks}) ORDER BY rm.person_id, rank, rm.rider_id",
            (company, *person_ids),
        ).fetchall()
    for r in rows:
        out.setdefault(int(r["person_id"]), r["rider_id"])
    return out


def parse_house_sheet(file_bytes: bytes, config: sqlite3.Row) -> ParseResult:
    company = config["company_name"]
    df = _with_header_row(_read(file_bytes))
    cols = _match_columns(df)
    missing = [k for k in _REQUIRED if k not in cols]
    if missing:
        raise ValueError(
            "The house sheet needs a Person ID column and a Gross payout column"
            + (f"; found only: {', '.join(cols.values()) or 'nothing recognisable'}")
        )
    result = ParseResult(company=company, sheet="house", matched_columns=dict(cols))

    rows: list[dict] = []
    for i, row in df.iterrows():
        pid_raw = row[cols["person_id"]]
        gross = _money(row[cols["gross"]])
        if (pid_raw is None or str(pid_raw).strip() in ("", "nan")) and gross is None:
            continue
        label = _norm(pid_raw)
        if label in ("total", "grand total", "sum") or (
            not label and "name" in cols and _norm(row[cols["name"]]) in ("total", "grand total")
        ):
            continue
        try:
            pid = int(float(str(pid_raw).strip()))
        except (TypeError, ValueError):
            result.warnings.append(f"Row {i + 2}: Person ID {pid_raw!r} is not a number — skipped")
            continue
        rows.append(
            {
                "line": i + 2,
                "pid": pid,
                "gross": gross,
                "rent": _money(row[cols["rent"]]) if "rent" in cols else None,
                "net": _money(row[cols["net"]]) if "net" in cols else None,
                "rider_id": (str(row[cols["rider_id"]]).strip() if "rider_id" in cols else "")
                or "",
                "name": (str(row[cols["name"]]).strip() if "name" in cols else "") or None,
            }
        )
    if not rows:
        raise ValueError("The house sheet has no rider rows")

    lookup = _resolve_rider_ids(company, sorted({r["pid"] for r in rows}))
    unplaced = []
    seen: set[int] = set()
    for r in rows:
        if r["pid"] in seen:
            result.warnings.append(f"Row {r['line']}: person {r['pid']} appears more than once")
        seen.add(r["pid"])
        rid = (
            r["rider_id"]
            if r["rider_id"] and r["rider_id"].lower() != "nan"
            else lookup.get(r["pid"])
        )
        if not rid:
            unplaced.append(
                f"row {r['line']}: person {r['pid']}" + (f" ({r['name']})" if r["name"] else "")
            )
            continue
        if r["gross"] is None:
            result.warnings.append(f"Row {r['line']}: {rid} has no gross payout — treated as 0")
        rec = RiderRecord(rider_id=rid, payout=r["gross"] or 0, name=r["name"])
        rec.sheet_rent = r["rent"]
        rec.sheet_net = r["net"]
        result.records.append(rec)
    if unplaced:
        raise ValueError(
            f"{len(unplaced)} row(s) name a person with no active rider id at {company}: "
            + "; ".join(unplaced[:8])
            + (" …" if len(unplaced) > 8 else "")
            + ". Give them an id at this company (Riders → Add at another company), or add a Rider ID column."  # noqa: E501
        )
    return result


def check_sheet_against_engine(records, rows) -> list[str]:
    """Warnings where the sheet's Rent charged / Net payout disagree with what
    the engine computed. ``rows`` are the engine's RiderResult rows."""
    by_rid = {r.rider_id: r for r in rows}
    out = []
    for rec in records:
        r = by_rid.get(rec.rider_id)
        if r is None:
            continue
        s_rent = getattr(rec, "sheet_rent", None)
        s_net = getattr(rec, "sheet_net", None)
        engine_rent = int(round(r.rent))  # RiderResult carries paise, like everything in the engine
        engine_net = int(round(r.released))
        if s_rent is not None and abs(s_rent - engine_rent) > 1:
            out.append(
                f"{r.name or rec.rider_id}: sheet says rent ₹{s_rent / 100:,.0f}, "
                f"engine charged ₹{engine_rent / 100:,.0f} from the vehicle's days — the ledger keeps the engine's figure"  # noqa: E501
            )
        if s_net is not None and abs(s_net - engine_net) > 1:
            out.append(
                f"{r.name or rec.rider_id}: sheet says net ₹{s_net / 100:,.0f}, "
                f"engine pays ₹{engine_net / 100:,.0f} after rent, arrears and holds"
            )
    return out
