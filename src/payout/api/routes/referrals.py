"""Rider referrals — who brought whom in, and the ₹1,000 bonus that follows.

Recruiters record a referral while onboarding (``POST /riders`` with
``referred_by_person_id``) or here afterwards; everyone can read them. The
bonus itself is paid by the payout engine (payout.domain.referrals).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from payout.api.auth import get_current_user, require_admin, require_recruiter
from payout.db import get_connection
from payout.domain.activity import record_activity
from payout.domain.referrals import (
    BONUS_PAISE,
    INSTALLMENT_PAISE,
    INSTALLMENTS,
    QUALIFY_DAYS,
    ReferralError,
    create_referral,
    get_referral,
    list_referrals,
)

router = APIRouter()


class ReferralIn(BaseModel):
    new_person_id: int
    referrer_person_id: int
    company: str | None = None
    note: str | None = None


@router.get("/rules")
def rules(_: dict = Depends(get_current_user)) -> dict:
    return {
        "qualify_days": QUALIFY_DAYS,
        "bonus": BONUS_PAISE,
        "installments": INSTALLMENTS,
        "installment_amount": INSTALLMENT_PAISE,
        "text": (
            f"When the new rider has worked {QUALIFY_DAYS} days (still active, at least one "
            f"payout), the referrer gets ₹{BONUS_PAISE // 100:,} in {INSTALLMENTS} instalments "
            f"of ₹{INSTALLMENT_PAISE // 100:,}: the first in the payout processed after the "
            "month is reached, the second in the next."
        ),
    }


@router.get("")
def list_all(
    person_id: int | None = Query(None, description="referrals where this person is either side"),
    status: str | None = None,
    mine: bool = Query(False, description="only referrals I recorded"),
    user: dict = Depends(get_current_user),
) -> list[dict]:
    with get_connection() as conn:
        return list_referrals(
            conn,
            person_id=person_id,
            status=status,
            created_by=user["email"] if mine else None,
        )


@router.post("", status_code=201)
def create(body: ReferralIn, user: dict = Depends(require_recruiter)) -> dict:
    with get_connection() as conn:
        try:
            ref = create_referral(
                conn,
                new_person_id=body.new_person_id,
                referrer_person_id=body.referrer_person_id,
                company=body.company,
                created_by=user["email"],
            )
        except ReferralError as exc:
            raise HTTPException(409 if "already" in str(exc) else 400, str(exc)) from exc
        if body.note:
            conn.execute("UPDATE referrals SET note=? WHERE id=?", (body.note.strip(), ref["id"]))
            ref["note"] = body.note.strip()
        record_activity(
            conn,
            user,
            "referral.create",
            entity_type="person",
            entity_id=str(body.new_person_id),
            label=ref["new_name"],
            person_id=body.new_person_id,
            details={
                "referrer_person_id": body.referrer_person_id,
                "referrer": ref["referrer_name"],
            },
        )
        conn.commit()
    return ref


@router.post("/{referral_id}/void")
def void(referral_id: int, user: dict = Depends(require_admin)) -> dict:
    """Admin: cancel a referral (nothing further is paid; what was paid stays)."""
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM referrals WHERE id=?", (referral_id,)).fetchone():
            raise HTTPException(404, "Referral not found")
        conn.execute("UPDATE referrals SET status='void' WHERE id=?", (referral_id,))
        ref = get_referral(conn, referral_id)
        record_activity(
            conn,
            user,
            "referral.void",
            entity_type="person",
            entity_id=str(ref["new_person_id"]),
            label=ref["new_name"],
            person_id=ref["new_person_id"],
        )
        conn.commit()
    return ref
