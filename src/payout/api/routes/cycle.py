"""Cycle routes: upload a company file, preview or commit, get the xlsx output."""

from __future__ import annotations

import base64
import dataclasses
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from payout.api.auth import get_current_user
from payout.api.schemas import RiderOverrideIn
from payout.domain.engine import CycleOverrides, RiderOverride, process_cycle
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
            waive_days=ov.waive_days, waive_all=ov.waive_all,
            rent_override=ov.rent_override,
            force_hold=ov.force_hold, force_release=ov.force_release,
        )
    return CycleOverrides(per_rider=per_rider, adjustments=data.get("adjustments", []) or [])


@router.post("/run")
async def run_cycle(
    company: str = Form(...),
    cycle_start: date = Form(...),
    cycle_end: date = Form(...),
    commit: bool = Form(False),
    overrides: str | None = Form(None),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> dict:
    """Process a company payout file.

    - `commit=false` (default) runs as a dry-run preview; nothing is written.
    - `commit=true` writes everything atomically AND returns the styled .xlsx as
      base64 in the response so the frontend can trigger a download.
    """
    if cycle_end < cycle_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cycle_end must be on or after cycle_start",
        )
    file_bytes = await file.read()
    if not file_bytes:
        raise HTTPException(status_code=400, detail="Empty file upload")

    cycle_overrides = _parse_overrides(overrides)
    try:
        result = process_cycle(
            company=company, cycle_start=cycle_start, cycle_end=cycle_end,
            file_bytes=file_bytes, overrides=cycle_overrides,
            created_by=user["email"], commit=commit,
        )
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
