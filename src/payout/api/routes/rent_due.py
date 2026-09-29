"""Weekly EV rent for direct-pay riders: preview, book, and the collection
sheet. Admin only; mounted with no_recruiter (money)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from payout.api.auth import get_current_user, require_admin
from payout.db import get_connection
from payout.domain.activity import record_activity
from payout.domain.rent_due import book_rent_due, last_week_end, scan_rent_due, week_bounds
from payout.exports import xlsx_response

router = APIRouter()


def _week(week_end: str | None) -> date:
    if not week_end:
        return last_week_end()
    try:
        d = date.fromisoformat(week_end)
    except ValueError as e:
        raise HTTPException(400, "week_end must be YYYY-MM-DD") from e
    if d.weekday() != 6:
        raise HTTPException(400, "week_end must be a Sunday")
    if d > date.today():
        raise HTTPException(400, "week_end is in the future")
    return d


class BookIn(BaseModel):
    week_end: str | None = None


@router.get("/preview")
def preview(week_end: str | None = None, user: dict = Depends(get_current_user)) -> dict:
    """Every direct-pay holder with unbooked days in the week, and what
    booking would write. Nothing is saved."""
    end = _week(week_end)
    start, _ = week_bounds(end)
    conn = get_connection()
    try:
        entries = scan_rent_due(conn, end)
    finally:
        conn.close()
    pending = [e for e in entries if not e["already_booked"]]
    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "entries": entries,
        # counts, named so the rupee middleware leaves them alone
        "pending_count": len(pending),
        "amount": sum(e["amount"] for e in pending),
        "booked_count": len(entries) - len(pending),
    }


@router.post("/book")
def book(body: BookIn, user: dict = Depends(require_admin)) -> dict:
    """Book the week's RENT_DUE for every direct-pay holder not yet booked."""
    end = _week(body.week_end)
    start, _ = week_bounds(end)
    conn = get_connection()
    try:
        booked = book_rent_due(conn, end, created_by=user["email"])
        if booked:
            record_activity(
                conn,
                user,
                "rent_due.book",
                entity_type="cycle",
                entity_id=f"rent-due@{end.isoformat()}",
                label=f"Rent due {start.isoformat()}..{end.isoformat()}: {len(booked)} rider(s)",
                details={
                    "week_end": end.isoformat(),
                    "count": len(booked),
                    "amount": sum(b["amount"] for b in booked),
                },  # noqa: E501
            )
        conn.commit()
    finally:
        conn.close()
    return {
        "week_start": start.isoformat(),
        "week_end": end.isoformat(),
        "booked": booked,
        "count": len(booked),
        "amount": sum(b["amount"] for b in booked),
    }


_SHEET_HEADERS = (
    "Name",
    "Person ID",
    "Rider ID",
    "Company",
    "Hub",
    "Phone",
    "EV ID",
    "Days this week",
    "Rent this week",
    "Arrears before this week",
    "To collect",
    "Booked?",
    "Collected ₹ (fill in)",
    "Collected by",
)


@router.post("/collection")
def collection(body: BookIn, user: dict = Depends(get_current_user)):
    """The Monday sheet for the hubs: who owes what in cash this week. Reads
    what ``preview`` shows; books nothing."""
    end = _week(body.week_end)
    start, _ = week_bounds(end)
    conn = get_connection()
    try:
        entries = scan_rent_due(conn, end)
    finally:
        conn.close()
    rows = []
    for e in sorted(entries, key=lambda x: ((x["hub"] or "~"), x["name"])):
        prior = e["arrears_outstanding"] - (e["amount"] if e["already_booked"] else 0)
        rows.append(
            (
                e["name"],
                e["person_id"],
                e["rider_id"],
                e["company"],
                e["hub"] or "",
                e["mob_no"] or "",
                e["ev_id"],
                e["days"],
                e["amount"],
                max(prior, 0),
                max(prior, 0) + e["amount"],
                "yes" if e["already_booked"] else "no",
                None,
                "",
            )
        )
    return xlsx_response(
        filename_stem=f"rent_collection_{start.isoformat()}_{end.isoformat()}",
        sheet_name="Collect",
        headers=_SHEET_HEADERS,
        rows=rows,
        numeric_cols=(8, 9, 10, 11, 13),
        totals_cols=(9, 10, 11),
        money_cols=(9, 10, 11, 13),
        left_align_cols=(1, 3, 4, 5, 7, 12, 14),
    )
