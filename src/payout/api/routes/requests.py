"""Money requests — the only way a recruiter touches money: by asking.

A recruiter can't post an adjustment, but they know things the office
doesn't ("he paid ₹500 cash for the helmet", "the deposit was refunded in
cash"). They file a request: person, credit or debit, amount, why. It sits
OPEN — highlighted on the person's profile and counted in the admin
attention strip — until an admin approves it (which posts the ledger
adjustment, optionally for a different amount) or rejects it with a note.

Routes (amounts are rupees at the API boundary, paise inside):
  GET  /api/requests?status=open&person_id=      list (recruiters: own only)
  GET  /api/requests/summary                     {"open": n}
  POST /api/requests                             recruiter+
  POST /api/requests/{request_id}/approve        admin
  POST /api/requests/{request_id}/reject         admin
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from payout.api.auth import get_current_user, require_admin, require_recruiter
from payout.db import get_connection
from payout.domain.activity import record_activity
from payout.domain.adjustments import post_adjustment
from payout.domain.arrears import settle_arrears_from_credit
from payout.money import to_paise

router = APIRouter()


class MoneyRequestIn(BaseModel):
    person_id: int
    direction: str  # credit | debit
    amount: float = Field(gt=0)  # rupees
    reason: str = Field(min_length=3, max_length=500)


class ResolveIn(BaseModel):
    note: str | None = None
    amount: float | None = Field(default=None, gt=0)  # rupees; approve with a different amount


_SELECT = (
    "SELECT r.id, r.created_at, r.created_by, r.person_id, pr.display_name AS person_name, "
    "       r.direction, r.amount, r.reason, r.status, r.resolved_by, r.resolved_at, "
    "       r.resolution_note, r.applied_amount "
    "FROM money_requests r JOIN person_registry pr ON pr.person_id = r.person_id "
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


@router.get("")
def list_requests(
    status: str | None = Query(default=None),
    person_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    user: dict = Depends(get_current_user),
) -> list[dict]:
    where, params = [], []
    if status:
        where.append("r.status=?")
        params.append(status)
    if person_id is not None:
        where.append("r.person_id=?")
        params.append(person_id)
    if user["role"] == "recruiter":
        where.append("r.created_by=?")
        params.append(user["email"])
    sql = _SELECT + (("WHERE " + " AND ".join(where)) if where else "")
    sql += " ORDER BY (r.status='open') DESC, r.created_at DESC, r.id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@router.get("/summary")
def request_summary(user: dict = Depends(get_current_user)) -> dict:
    """Open-request count for badges; recruiters count only their own."""
    with get_connection() as conn:
        if user["role"] == "recruiter":
            n = conn.execute(
                "SELECT COUNT(*) FROM money_requests WHERE status='open' AND created_by=?",
                (user["email"],),
            ).fetchone()[0]
        else:
            n = conn.execute("SELECT COUNT(*) FROM money_requests WHERE status='open'").fetchone()[
                0
            ]
    return {"open": int(n)}


@router.post("", status_code=201)
def create_request(body: MoneyRequestIn, user: dict = Depends(require_recruiter)) -> dict:
    direction = body.direction.strip().lower()
    if direction not in ("credit", "debit"):
        raise HTTPException(400, "direction must be 'credit' or 'debit'")
    with get_connection() as conn:
        person = conn.execute(
            "SELECT display_name FROM person_registry WHERE person_id=?", (body.person_id,)
        ).fetchone()
        if not person:
            raise HTTPException(404, f"Person {body.person_id} not found")
        cur = conn.execute(
            "INSERT INTO money_requests (created_by, person_id, direction, amount, reason) "
            "VALUES (?,?,?,?,?)",
            (user["email"], body.person_id, direction, to_paise(body.amount), body.reason.strip()),
        )
        rid = cur.lastrowid
        record_activity(
            conn,
            user,
            "request.create",
            entity_type="request",
            entity_id=rid,
            label=f"{direction} ₹{body.amount:,.2f} — {person['display_name']}",
            person_id=body.person_id,
            details={
                "direction": direction,
                "rupees": body.amount,
                "reason": body.reason,
            },
        )
        row = conn.execute(_SELECT + "WHERE r.id=?", (rid,)).fetchone()
        conn.commit()
    return dict(row)


def _load_open(conn, request_id: int):
    row = conn.execute(_SELECT + "WHERE r.id=?", (request_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Request not found")
    if row["status"] != "open":
        raise HTTPException(409, f"Request is already {row['status']}")
    return row


@router.post("/{request_id}/approve")
def approve_request(
    request_id: int, body: ResolveIn | None = None, user: dict = Depends(require_admin)
) -> dict:
    """Post the adjustment the recruiter asked for (or the amount the admin
    chooses) and close the request."""
    body = body or ResolveIn()
    with get_connection() as conn:
        req = _load_open(conn, request_id)
        paise = to_paise(body.amount) if body.amount is not None else int(req["amount"])
        signed = paise if req["direction"] == "credit" else -paise
        reason = f"Request #{request_id} by {req['created_by']}: {req['reason']}"
        if body.note:
            reason += f" — {body.note}"
        new_balance = post_adjustment(
            conn, req["person_id"], signed, reason, user["email"], rider_id="", company=""
        )
        settled = 0
        if (new_balance or 0) > 0:
            settled = settle_arrears_from_credit(conn, req["person_id"], created_by=user["email"])
        conn.execute(
            "UPDATE money_requests SET status='approved', resolved_by=?, resolved_at=?, "
            "resolution_note=?, applied_amount=? WHERE id=?",
            (user["email"], _now(), body.note, paise, request_id),
        )
        record_activity(
            conn,
            user,
            "request.approve",
            entity_type="request",
            entity_id=request_id,
            label=f"{req['direction']} — {req['person_name']}",
            person_id=req["person_id"],
            details={
                "requested_rupees": int(req["amount"]) / 100,
                "applied_rupees": paise / 100,
                "requested_by": req["created_by"],
                "note": body.note,
            },
        )
        row = conn.execute(_SELECT + "WHERE r.id=?", (request_id,)).fetchone()
        conn.commit()
    out = dict(row)
    out["new_balance"] = new_balance
    out["arrears_settled_from_credit"] = settled
    return out


@router.post("/{request_id}/reject")
def reject_request(
    request_id: int, body: ResolveIn | None = None, user: dict = Depends(require_admin)
) -> dict:
    body = body or ResolveIn()
    with get_connection() as conn:
        req = _load_open(conn, request_id)
        conn.execute(
            "UPDATE money_requests SET status='rejected', resolved_by=?, resolved_at=?, "
            "resolution_note=? WHERE id=?",
            (user["email"], _now(), body.note, request_id),
        )
        record_activity(
            conn,
            user,
            "request.reject",
            entity_type="request",
            entity_id=request_id,
            label=f"{req['direction']} — {req['person_name']}",
            person_id=req["person_id"],
            details={"requested_by": req["created_by"], "note": body.note},
        )
        row = conn.execute(_SELECT + "WHERE r.id=?", (request_id,)).fetchone()
        conn.commit()
    return dict(row)
