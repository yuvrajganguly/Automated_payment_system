"""Ledger routes: per-person transactions, manual adjustments."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from payout.api.auth import get_current_user, require_admin
from payout.api.schemas import AdjustmentIn, TransactionOut
from payout.db import get_connection
from payout.domain.adjustments import post_adjustment

router = APIRouter()


@router.get("", response_model=list[TransactionOut])
def list_recent_transactions(
    event_type: Optional[str] = None,
    company: Optional[str] = None,
    limit: int = 200,
    _: dict = Depends(get_current_user),
) -> list[TransactionOut]:
    """Global transaction feed across all persons (newest first)."""
    sql = (
        "SELECT id, person_id, rider_id, company, cycle_start, cycle_end, event_type, "
        "amount, balance_after, days, remarks, created_at, created_by "
        "FROM transactions WHERE 1=1 "
    )
    params: list = []
    if event_type:
        sql += " AND event_type=? "; params.append(event_type)
    if company:
        sql += " AND company=? "; params.append(company)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(max(limit, 1), 1000))
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [TransactionOut(**dict(r)) for r in rows]


@router.get("/{person_id}", response_model=list[TransactionOut])
def get_ledger(
    person_id: int,
    event_type: Optional[str] = None,
    limit: int = 200,
    _: dict = Depends(get_current_user),
) -> list[TransactionOut]:
    sql = (
        "SELECT id, person_id, rider_id, company, cycle_start, cycle_end, event_type, "
        "amount, balance_after, days, remarks, created_at, created_by "
        "FROM transactions WHERE person_id=? "
    )
    params: list = [person_id]
    if event_type:
        sql += " AND event_type=? "; params.append(event_type)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [TransactionOut(**dict(r)) for r in rows]


@router.post("/adjustments")
def post_adjustment_endpoint(body: AdjustmentIn,
                             user: dict = Depends(require_admin)) -> dict:
    if not body.reason:
        raise HTTPException(400, "Reason is required")
    if not body.amount:
        raise HTTPException(400, "Amount cannot be zero")
    with get_connection() as conn:
        pid = body.person_id
        if not pid and body.rider_id:
            if body.company:
                row = conn.execute(
                    "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
                    (body.rider_id, body.company)).fetchone()
            else:
                row = conn.execute(
                    "SELECT person_id FROM rider_master WHERE rider_id=? LIMIT 1",
                    (body.rider_id,)).fetchone()
            if row:
                pid = row["person_id"]
        if not pid:
            raise HTTPException(404, "Person not found (provide person_id or rider_id)")
        new_balance = post_adjustment(
            conn, pid, body.amount, body.reason, user["email"],
            rider_id=body.rider_id or "", company=body.company or "",
        )
        conn.commit()
    return {"person_id": pid, "amount": body.amount, "new_balance": new_balance}
