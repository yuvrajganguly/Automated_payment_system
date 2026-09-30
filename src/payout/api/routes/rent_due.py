"""Weekly EV rent for direct-pay riders: preview, book, and the collection
sheet. Admin only; mounted with no_recruiter (money)."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from payout.api.auth import get_current_user, require_admin
from payout.db import get_connection
from payout.domain.activity import record_activity
from payout.domain.rent_due import book_rent_due, last_week_end, scan_rent_due, week_bounds
from payout.exports import xlsx_response
from payout.money import to_paise

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


@router.post("/collection/upload")
async def collection_upload(
    file: UploadFile = File(...), user: dict = Depends(require_admin)
) -> dict:
    """The collection sheet, back from the hub with "Collected ₹" filled in.
    Every row with an amount becomes a cash receipt through the ordinary
    manual-payment path (arrears first), under the uploader's name. Rows
    with nothing collected are left alone; a row that fails is reported and
    the rest still land."""
    import io

    import pandas as pd

    from payout.api.routes.ledger import post_rent_payment
    from payout.api.schemas import RentPaymentIn

    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    try:
        df = pd.read_excel(io.BytesIO(raw))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Could not read the sheet: {e}") from e
    cols = {str(c).strip().lower(): c for c in df.columns}
    pid_col = next((cols[c] for c in cols if c in ("person id", "person_id")), None)
    amt_col = next(
        (
            cols[c]
            for c in cols
            if c.startswith("collected ₹") or c in ("collected", "collected rs")
        ),
        None,
    )
    if pid_col is None or amt_col is None:
        raise HTTPException(
            400, "The sheet needs the Person ID column and the 'Collected ₹' column"
        )
    by_col = next((cols[c] for c in cols if c == "collected by"), None)
    week_col = next((cols[c] for c in cols if c == "ev id"), None)
    booked, skipped, failed = [], 0, []
    for i, row in df.iterrows():
        pid_raw, amt_raw = row[pid_col], row[amt_col]
        if pd.isna(pid_raw) or str(pid_raw).strip() in ("", "TOTAL"):
            continue
        if pd.isna(amt_raw) or str(amt_raw).strip() in ("", "-", "–"):
            skipped += 1
            continue
        try:
            pid = int(float(pid_raw))
            amount = float(str(amt_raw).replace(",", "").replace("₹", ""))  # rupees, as typed
            if amount <= 0:
                skipped += 1
                continue
            who = (
                str(row[by_col]).strip() if by_col is not None and not pd.isna(row[by_col]) else ""
            )
            ev = (
                str(row[week_col]).strip()
                if week_col is not None and not pd.isna(row[week_col])
                else ""
            )
            body = RentPaymentIn(
                person_id=pid,
                amount=amount,
                paid_on=None,
                period_start=None,
                period_end=None,
                force_advance=False,
                remarks="Collection sheet"
                + (f" ({file.filename})" if file.filename else "")
                + (f" · {ev}" if ev else "")
                + (f" · collected by {who}" if who else ""),
            )
            r = post_rent_payment(body, user)
            booked.append(
                {
                    "person_id": pid,
                    "amount": to_paise(amount),  # paise, like every money field the edge converts
                    "applied_to_arrears": r.get("applied_to_arrears"),
                    "applied_to_rent": r.get("applied_to_rent"),
                }
            )
        except HTTPException as e:
            failed.append({"row": int(i) + 2, "person_id": str(pid_raw), "error": str(e.detail)})
        except Exception as e:  # noqa: BLE001 — one bad row must not lose the others
            failed.append({"row": int(i) + 2, "person_id": str(pid_raw), "error": str(e)})
    return {
        "count": len(booked),
        "amount": sum(b["amount"] for b in booked),
        "receipts": booked,
        "skipped": skipped,
        "failed": failed,
    }
