"""Cycle routes: upload a company file, preview or commit, get the xlsx output."""

from __future__ import annotations

import base64
import dataclasses
import io
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from payout.api.auth import require_admin
from payout.api.schemas import RiderOverrideIn
from payout.db import get_connection
from payout.domain.engine import (
    CycleAlreadyCommitted,
    CycleOverrides,
    RiderOverride,
    process_cycle,
)
from payout.money import to_paise
from payout.output import build_output, build_output_filename

router = APIRouter()


def _json_safe(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(x) for x in value]
    return value


def _serialize(result) -> dict:
    return _json_safe(dataclasses.asdict(result))


def _parse_overrides(raw: str | None) -> CycleOverrides:
    """Accepts a JSON string: {"per_rider": [...], "adjustments": [...]}."""
    if not raw:
        return CycleOverrides()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid overrides JSON: {exc.msg}",
        ) from exc

    per_rider: dict[str, RiderOverride] = {}
    for item in data.get("per_rider", []) or []:
        ov = RiderOverrideIn.model_validate(item)
        per_rider[ov.rider_id] = RiderOverride(
            waive_days=ov.waive_days,
            waive_all=ov.waive_all,
            rent_override=(to_paise(ov.rent_override) if ov.rent_override is not None else None),
            force_hold=ov.force_hold,
            force_release=ov.force_release,
        )
    return CycleOverrides(per_rider=per_rider, adjustments=data.get("adjustments", []) or [])


def _orders_to_parse_result(company: str, raw: str | None, rate_paise: int | None):
    """Turn the typed order counts into the records a payout file would give.

    Payout = orders × rate in paise, exactly what a parsed file yields. A rider
    listed twice is summed; zero-order riders are kept so the cycle treats
    them as present (no rent missed for being absent)."""
    from payout.domain.models import ParseResult, RiderRecord

    if not rate_paise:
        raise HTTPException(400, f"{company} has no per-order rate set (Admin → Companies).")
    if not raw:
        raise HTTPException(400, f"{company} is paid per order — enter the order counts.")
    try:
        items = json.loads(raw)
        assert isinstance(items, list)
    except (ValueError, AssertionError) as exc:
        raise HTTPException(400, "orders must be a JSON list of {rider_id, orders}") from exc
    counts: dict[str, float] = {}
    for it in items:
        rid = str((it or {}).get("rider_id", "")).strip()
        if not rid:
            continue
        try:
            n = float(it.get("orders") or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"orders for {rid} is not a number") from exc
        if n < 0:
            raise HTTPException(400, f"orders for {rid} cannot be negative")
        counts[rid] = counts.get(rid, 0.0) + n
    if not counts:
        raise HTTPException(400, "No riders with order counts were given.")
    # Parsed records carry paise (the parsers call to_paise); do the same.
    records = [
        RiderRecord(rider_id=rid, payout=int(round(n * rate_paise)), orders=n)
        for rid, n in counts.items()
    ]
    rate = rate_paise / 100.0
    return ParseResult(
        company=company,
        records=records,
        sheet="orders entered by hand",
        matched_columns={
            "rider_id": "rider_id",
            "payout": f"orders × ₹{rate:g}",
            "orders": "orders",
        },
        warnings=[],
    )


def _salary_to_parse_result(conn, company: str, raw: str | None, co) -> tuple[object, list[dict]]:
    """Salaried company: the office marks days present and orders per rider.

    Per rider (salary from the rider row, paise per cycle):
        days_off   = max(0, expected_days − days_present)
        base_pay   = salary − days_off × salary / expected_days
        incentives = orders × incentive_per_order + days_present × incentive_per_day
        payout     = base_pay + incentives
    Returns the ParseResult for the engine and the working per rider."""
    from payout.domain.models import ParseResult, RiderRecord

    if not raw:
        raise HTTPException(400, f"{company} is salaried — mark days present and orders.")
    try:
        items = json.loads(raw)
        assert isinstance(items, list)
    except (ValueError, AssertionError) as exc:
        raise HTTPException(
            400, "attendance must be a JSON list of {rider_id, days_present, orders}"
        ) from exc
    expected = int(co["salary_expected_days"] or 26)
    inc_order = int(co["incentive_per_order"] or 0)
    inc_day = int(co["incentive_per_day"] or 0)
    salaries = {
        r["rider_id"]: (int(r["salary"] or 0), r["person_id"], r["name"])
        for r in conn.execute(
            "SELECT rider_id, salary, person_id, name FROM rider_master WHERE company=?",
            (company,),
        )
    }
    seen: dict[str, dict] = {}
    for it in items:
        rid = str((it or {}).get("rider_id", "")).strip()
        if not rid:
            continue
        try:
            present = float(it.get("days_present") or 0)
            n_orders = float(it.get("orders") or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"days/orders for {rid} are not numbers") from exc
        if present < 0 or n_orders < 0:
            raise HTTPException(400, f"days/orders for {rid} cannot be negative")
        if present > 31:
            raise HTTPException(400, f"days present for {rid} cannot exceed 31")
        if rid in seen:
            seen[rid]["days_present"] += present
            seen[rid]["orders"] += n_orders
        else:
            seen[rid] = {"rider_id": rid, "days_present": present, "orders": n_orders}
    if not seen:
        raise HTTPException(400, "No riders were marked.")
    records, lines = [], []
    for rid, it in seen.items():
        salary, pid, name = salaries.get(rid, (0, None, None))
        if rid in salaries and not salary:
            raise HTTPException(
                400, f"{name or rid} has no salary set — enter it in the table first."
            )
        days_off = max(0.0, expected - it["days_present"])
        base = int(round(salary - days_off * salary / expected))
        base = max(0, base)
        incentives = int(round(it["orders"] * inc_order + it["days_present"] * inc_day))
        payout = base + incentives
        records.append(RiderRecord(rider_id=rid, payout=payout, orders=it["orders"]))
        lines.append(
            {
                "rider_id": rid,
                "person_id": pid,
                "name": name,
                "days_present": it["days_present"],
                "days_off": days_off,
                "orders": it["orders"],
                "salary": salary,
                "base_pay": base,
                "incentives": incentives,
                "payout": payout,
            }
        )
    parsed = ParseResult(
        company=company,
        records=records,
        sheet="attendance marked by hand",
        matched_columns={
            "rider_id": "rider_id",
            "payout": "salary − days off + incentives",
            "orders": "orders",
        },
        warnings=[],
    )
    return parsed, lines


def _record_salary_inputs(company, cycle_start, cycle_end, lines, user) -> None:
    """Keep what was marked for the cycle (after a successful commit)."""
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM salary_inputs WHERE company=? AND cycle_start=? AND cycle_end=?",
            (company, cycle_start.isoformat(), cycle_end.isoformat()),
        )
        for ln in lines:
            conn.execute(
                "INSERT INTO salary_inputs (company, cycle_start, cycle_end, rider_id, "
                " person_id, days_present, orders, salary, base_pay, incentives, payout, "
                " created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    company,
                    cycle_start.isoformat(),
                    cycle_end.isoformat(),
                    ln["rider_id"],
                    ln["person_id"],
                    ln["days_present"],
                    ln["orders"],
                    ln["salary"],
                    ln["base_pay"],
                    ln["incentives"],
                    ln["payout"],
                    user["email"],
                ),
            )
        conn.commit()


_SHEET_ID_ALIASES = ("rider_id", "rider id", "id", "worker code", "rider", "fe id", "employee id")
_SHEET_DAYS_ALIASES = (
    "days_present",
    "days present",
    "present",
    "attendance",
    "days",
    "present days",
)
_SHEET_ORDERS_ALIASES = ("orders", "orders delivered", "delivered", "deliveries", "total orders")
_SHEET_NAME_ALIASES = ("name", "rider name", "rider_name")


@router.post("/parse-sheet")
async def parse_attendance_sheet(
    company: str = Form(...),
    file: UploadFile = File(...),
    _: dict = Depends(require_admin),
) -> dict:
    """Read an attendance / orders sheet the office keeps (xlsx or csv) into
    rows the Process Payout table can take: {rider_id, name, days_present,
    orders}. Column headers are matched loosely; unmatched rider ids are
    reported so the operator can fix the sheet rather than lose rows."""
    import pandas as pd

    from payout.parsers.base import match_column

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    try:
        if (file.filename or "").lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(raw))
        else:
            df = pd.read_excel(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not read the sheet: {exc}") from exc
    df.columns = [str(c).strip() for c in df.columns]
    id_col = match_column(df.columns, *_SHEET_ID_ALIASES)
    if not id_col:
        raise HTTPException(
            400, "No rider-id column found (expected a header like 'Rider ID' or 'ID')."
        )
    days_col = match_column(df.columns, *_SHEET_DAYS_ALIASES)
    orders_col = match_column(df.columns, *_SHEET_ORDERS_ALIASES)
    name_col = match_column(df.columns, *_SHEET_NAME_ALIASES)
    with get_connection() as conn:
        known = {
            r["rider_id"]: r["name"]
            for r in conn.execute(
                "SELECT rider_id, name FROM rider_master WHERE company=? AND is_active=1",
                (company,),
            )
        }

    def num(rec, col):
        if not col:
            return None
        try:
            f = float(rec.get(col))
        except (TypeError, ValueError):
            return None
        return None if f != f else f  # NaN

    rows, unknown = [], []
    for _, r in df.iterrows():
        rid = str(r.get(id_col, "") or "").strip()
        if rid.endswith(".0") and rid[:-2].isdigit():
            rid = rid[:-2]
        if not rid or rid.lower() == "nan":
            continue
        nm = str(r.get(name_col) or "").strip() if name_col else ""
        row = {
            "rider_id": rid,
            "name": (nm if nm and nm.lower() != "nan" else "") or known.get(rid),
            "days_present": num(r, days_col),
            "orders": num(r, orders_col),
        }
        (rows if rid in known else unknown).append(row)
    return {
        "rows": rows,
        "unknown": unknown,
        "matched": {"rider_id": id_col, "days_present": days_col, "orders": orders_col},
    }


@router.post("/run")
async def run_cycle(
    company: str = Form(...),
    cycle_start: date = Form(...),
    cycle_end: date = Form(...),
    commit: bool = Form(False),
    force: bool = Form(False),
    overrides: str | None = Form(None),
    orders: str | None = Form(None),
    attendance: str | None = Form(None),
    file: UploadFile | None = File(None),
    user: dict = Depends(require_admin),
) -> dict:
    """Process a company cycle.

    Payout-file companies send `file` (their .xlsx). Per-order companies send
    `orders` instead — a JSON list of {"rider_id", "orders"} typed off the
    company's dashboard; the payout is orders × the company's per-order rate.
    Direct-pay companies have nothing to process and are refused.

    - `commit=false` (default) runs as a dry-run preview; nothing is written.
    - `commit=true` writes everything atomically AND returns the styled .xlsx as
      base64 in the response so the frontend can trigger a download.
    """
    if cycle_end < cycle_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cycle_end must be on or after cycle_start",
        )
    # Guard: a cycle whose end is meaningfully in the future would write
    # 'billed' day-rows for days that haven't happened yet. If a return or
    # maintenance fires between now and cycle_end those rows go stale. Allow
    # a 3-day grace so timezone / "the file just landed at 11:59pm" cases
    # work, but refuse anything farther out.
    from datetime import date as _date_cls
    from datetime import timedelta as _td

    today = _date_cls.today()
    if cycle_end > today + _td(days=3):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"cycle_end ({cycle_end}) is more than 3 days in the future. "
                "Future-dated cycles write daily-ledger rows for days that "
                "haven't happened — returns or maintenance after today would "
                "leave the ledger stale. Wait until the cycle's actually closed."
            ),
        )
    with get_connection() as conn:
        co = conn.execute(
            "SELECT payment_model, per_order_rate, is_active, salary_expected_days, "
            " incentive_per_order, incentive_per_day FROM companies WHERE company_name=?",
            (company,),
        ).fetchone()
        if not co or not co["is_active"]:
            raise HTTPException(400, f"Company '{company}' not found or not active.")
        model = co["payment_model"] or "payout_file"
        salary_lines: list[dict] = []
        if model == "salary":
            parsed, salary_lines = _salary_to_parse_result(conn, company, attendance, co)
    file_bytes: bytes | None = None
    if model != "salary":
        parsed = None
    if model == "direct":
        raise HTTPException(
            400,
            f"{company} pays its riders directly — there is no payout to process. "
            "Change how it pays under Admin → Companies if that is wrong.",
        )
    if model == "per_order":
        parsed = _orders_to_parse_result(company, orders, co["per_order_rate"])
    elif model == "salary":
        pass
    else:
        if file is None:
            raise HTTPException(400, f"{company} sends a payout file — upload it to process.")
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty file upload")

    cycle_overrides = _parse_overrides(overrides)
    try:
        result = process_cycle(
            company=company,
            cycle_start=cycle_start,
            cycle_end=cycle_end,
            file_bytes=file_bytes,
            parsed=parsed,
            overrides=cycle_overrides,
            created_by=user["email"],
            commit=commit,
            force=force,
        )
    except CycleAlreadyCommitted as exc:
        # Guard lives in the engine's transaction now (was a racy pre-check here).
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response: dict = {"result": _serialize(result)}
    if salary_lines:
        response["salary_lines"] = salary_lines
        if commit and result.committed:
            _record_salary_inputs(company, cycle_start, cycle_end, salary_lines, user)
    if commit:
        buf = build_output(result)
        response["xlsx"] = {
            "filename": build_output_filename(company, cycle_start, cycle_end),
            "content_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    return response
