"""EV requests — a recruiter asking the office for vehicles.

A recruiter can't allot an EV; the units are handed out from the office. But
they are the ones standing in the store hearing "I'll join if you give me a
bike". So they file a request: how many EVs, for which store, and why. It
sits OPEN until an admin fulfils it (possibly for fewer units than asked) or
rejects it with a note; the recruiter can withdraw their own open request.

Nothing on the ledger moves here — this is a queue for the fleet desk, next
to the money requests recruiters already file.

Routes (counts, not money — no rupee conversion):
  GET  /api/ev-requests?status=open&zone=North    list (recruiters: own only)
  GET  /api/ev-requests/summary                   {"open": n, "units": n}
  POST /api/ev-requests                           recruiter+
  POST /api/ev-requests/{id}/fulfil               admin
  POST /api/ev-requests/{id}/reject               admin
  POST /api/ev-requests/{id}/cancel               the recruiter who filed it, or admin
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from payout.api.auth import get_current_user, require_admin, require_recruiter
from payout.api.routes.hubs import zone_filter
from payout.db import get_connection
from payout.domain.activity import record_activity

router = APIRouter()

MAX_UNITS = 25  # a request for more than this is a typo, not a plan


class EvRequestIn(BaseModel):
    quantity: int = Field(ge=1, le=MAX_UNITS)
    hub: str | None = None
    company: str | None = None
    note: str | None = Field(default=None, max_length=500)


class ResolveIn(BaseModel):
    note: str | None = None
    quantity: int | None = Field(default=None, ge=0, le=MAX_UNITS)  # fulfil fewer than asked


_SELECT = (
    "SELECT id, created_at, created_by, quantity, hub, company, zone, note, status, "
    "       fulfilled_quantity, resolved_by, resolved_at, resolution_note "
    "FROM ev_requests "
)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _zone_for(conn, company: str | None, hub: str | None, user: dict) -> str | None:
    """The store's zone if we know it, else the recruiter's own zone."""
    if hub:
        sql = "SELECT zone FROM company_hubs WHERE hub=? AND zone IS NOT NULL"
        params: list[object] = [hub]
        if company:
            sql += " AND company=?"
            params.append(company)
        row = conn.execute(sql + " LIMIT 1", params).fetchone()
        if row and row["zone"]:
            return str(row["zone"])
    return user.get("zone")


@router.get("")
def list_ev_requests(
    status: str | None = Query(default=None),
    zone: str | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    user: dict = Depends(get_current_user),
) -> list[dict]:
    where: list[str] = []
    params: list[object] = []
    if status:
        where.append("status=?")
        params.append(status)
    z = zone_filter(zone)
    if z == "unassigned":
        where.append("zone IS NULL")
    elif z:
        where.append("zone=?")
        params.append(z.title())
    if user["role"] == "recruiter":
        where.append("created_by=?")
        params.append(user["email"])
    sql = _SELECT + (("WHERE " + " AND ".join(where)) if where else "")
    sql += " ORDER BY (status='open') DESC, created_at DESC, id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


@router.get("/summary")
def ev_request_summary(user: dict = Depends(get_current_user)) -> dict:
    """Open requests and the units they add up to — for the attention strip."""
    sql = (
        "SELECT COUNT(*) AS n, COALESCE(SUM(quantity), 0) AS units "
        "FROM ev_requests WHERE status='open'"
    )
    params: list[object] = []
    if user["role"] == "recruiter":
        sql += " AND created_by=?"
        params.append(user["email"])
    with get_connection() as conn:
        row = conn.execute(sql, params).fetchone()
    return {"open": int(row["n"] or 0), "units": int(row["units"] or 0)}


@router.post("", status_code=201)
def create_ev_request(body: EvRequestIn, user: dict = Depends(require_recruiter)) -> dict:
    hub = (body.hub or "").strip() or None
    company = (body.company or "").strip() or None
    note = (body.note or "").strip() or None
    with get_connection() as conn:
        if (
            company
            and not conn.execute(
                "SELECT 1 FROM companies WHERE company_name=?", (company,)
            ).fetchone()
        ):
            raise HTTPException(404, f"Company {company!r} not found")
        zone = _zone_for(conn, company, hub, user)
        cur = conn.execute(
            "INSERT INTO ev_requests (created_by, quantity, hub, company, zone, note) "
            "VALUES (?,?,?,?,?,?)",
            (user["email"], body.quantity, hub, company, zone, note),
        )
        rid = cur.lastrowid
        where = hub or zone or "no store given"
        record_activity(
            conn,
            user,
            "ev_request.create",
            entity_type="ev_request",
            entity_id=rid,
            label=f"{body.quantity} EV{'s' if body.quantity > 1 else ''} — {where}",
            details={"quantity": body.quantity, "hub": hub, "zone": zone, "note": note},
        )
        row = conn.execute(_SELECT + "WHERE id=?", (rid,)).fetchone()
        conn.commit()
    return dict(row)


def _load_open(conn, request_id: int):
    row = conn.execute(_SELECT + "WHERE id=?", (request_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Request not found")
    if row["status"] != "open":
        raise HTTPException(409, f"Request is already {row['status']}")
    return row


def _resolve(
    request_id: int,
    status: str,
    action: str,
    body: ResolveIn,
    user: dict,
    fulfilled: int | None = None,
) -> dict:
    with get_connection() as conn:
        req = _load_open(conn, request_id)
        note = (body.note or "").strip() or None
        conn.execute(
            "UPDATE ev_requests SET status=?, resolved_by=?, resolved_at=?, resolution_note=?, "
            "fulfilled_quantity=? WHERE id=?",
            (status, user["email"], _now(), note, fulfilled, request_id),
        )
        record_activity(
            conn,
            user,
            action,
            entity_type="ev_request",
            entity_id=request_id,
            label=f"{req['quantity']} EV{'s' if req['quantity'] > 1 else ''} — "
            f"{req['hub'] or req['zone'] or 'no store'}",
            details={
                "asked": req["quantity"],
                "given": fulfilled,
                "requested_by": req["created_by"],
                "note": note,
            },
        )
        row = conn.execute(_SELECT + "WHERE id=?", (request_id,)).fetchone()
        conn.commit()
    return dict(row)


@router.post("/{request_id}/fulfil")
def fulfil_ev_request(
    request_id: int, body: ResolveIn | None = None, user: dict = Depends(require_admin)
) -> dict:
    """Mark the units as handed over. The actual allotment still happens on the
    EV pages — this only closes the ask."""
    body = body or ResolveIn()
    with get_connection() as conn:
        asked = _load_open(conn, request_id)["quantity"]
    given = int(body.quantity) if body.quantity is not None else int(asked)
    return _resolve(request_id, "fulfilled", "ev_request.fulfil", body, user, fulfilled=given)


@router.post("/{request_id}/reject")
def reject_ev_request(
    request_id: int, body: ResolveIn | None = None, user: dict = Depends(require_admin)
) -> dict:
    return _resolve(request_id, "rejected", "ev_request.reject", body or ResolveIn(), user)


@router.post("/{request_id}/cancel")
def cancel_ev_request(
    request_id: int, body: ResolveIn | None = None, user: dict = Depends(require_recruiter)
) -> dict:
    """Withdraw a request you filed (admins can withdraw anyone's)."""
    with get_connection() as conn:
        req = _load_open(conn, request_id)
    if user["role"] == "recruiter" and req["created_by"] != user["email"]:
        raise HTTPException(403, "That request was filed by someone else")
    return _resolve(request_id, "cancelled", "ev_request.cancel", body or ResolveIn(), user)
