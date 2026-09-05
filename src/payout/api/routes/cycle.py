"""Cycle routes: upload a company file, preview or commit, get the xlsx output."""

from __future__ import annotations

import base64
import dataclasses
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


@router.post("/run")
async def run_cycle(
    company: str = Form(...),
    cycle_start: date = Form(...),
    cycle_end: date = Form(...),
    commit: bool = Form(False),
    force: bool = Form(False),
    overrides: str | None = Form(None),
    orders: str | None = Form(None),
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
            "SELECT payment_model, per_order_rate, is_active FROM companies WHERE company_name=?",
            (company,),
        ).fetchone()
    if not co or not co["is_active"]:
        raise HTTPException(400, f"Company '{company}' not found or not active.")
    model = co["payment_model"] or "payout_file"
    file_bytes: bytes | None = None
    parsed = None
    if model == "direct":
        raise HTTPException(
            400,
            f"{company} pays its riders directly — there is no payout to process. "
            "Change how it pays under Admin → Companies if that is wrong.",
        )
    if model == "per_order":
        parsed = _orders_to_parse_result(company, orders, co["per_order_rate"])
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
    if commit:
        buf = build_output(result)
        response["xlsx"] = {
            "filename": build_output_filename(company, cycle_start, cycle_end),
            "content_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    return response
