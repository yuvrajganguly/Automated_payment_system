"""Company config routes."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from payout.api.auth import get_current_user
from payout.api.schemas import CompanyOut
from payout.db import get_connection
from payout.domain.cycles import next_cycle_for

router = APIRouter()


@router.get("", response_model=list[CompanyOut])
def list_companies(_: dict = Depends(get_current_user)) -> list[CompanyOut]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT company_name, parser_type, payout_column, has_hold_sheet, "
            "hold_style, is_active, rider_ids_shared_with FROM companies "
            "ORDER BY is_active DESC, company_name"
        ).fetchall()
    return [
        CompanyOut(
            company_name=r["company_name"],
            parser_type=r["parser_type"],
            payout_column=r["payout_column"],
            has_hold_sheet=bool(r["has_hold_sheet"]),
            hold_style=r["hold_style"],
            is_active=bool(r["is_active"]),
            rider_ids_shared_with=r["rider_ids_shared_with"],
        )
        for r in rows
    ]


@router.get("/{company_name}/next-cycle")
def get_next_cycle(company_name: str, _: dict = Depends(get_current_user)) -> dict:
    """Return the next (cycle_start, cycle_end) for the given company.

    Reads MAX(cycle_end) from the transactions table for this company. If the
    company has no history yet, anchors on today using the company's cadence.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM companies WHERE company_name = ?", (company_name,)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"Unknown company: {company_name!r}")
        latest = conn.execute(
            "SELECT MAX(cycle_end) AS last_end FROM transactions "
            "WHERE company = ? AND event_type IN ('PAYOUT','RENT','RENT_MISSED','RENT_RECOVERED','DUES_CARRY')",  # noqa: E501
            (company_name,),
        ).fetchone()
    last_end: date | None = None
    if latest and latest["last_end"]:
        try:
            last_end = date.fromisoformat(latest["last_end"])
        except ValueError:
            last_end = None
    start, end = next_cycle_for(company_name, last_end)
    return {
        "company_name": company_name,
        "last_cycle_end": last_end.isoformat() if last_end else None,
        "cycle_start": start.isoformat(),
        "cycle_end": end.isoformat(),
    }
