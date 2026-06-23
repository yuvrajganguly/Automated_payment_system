"""EV models, units, assignments and maintenance."""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from payout.api.auth import get_current_user, require_admin
from payout.api.schemas import (
    EvAssignIn, EvModelOut, EvReturnIn, EvUnitIn, EvUnitOut,
    MaintenanceClose, MaintenanceIn, MaintenanceOut,
)
from payout.db import get_connection
from payout.domain.adjustments import log_maintenance
from payout.exports import xlsx_response

router = APIRouter()


@router.get("/models", response_model=list[EvModelOut])
def list_ev_models(_: dict = Depends(get_current_user)) -> list[EvModelOut]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT model_id, provider, model_name, weekly_rate FROM ev_models "
            "ORDER BY provider, model_name").fetchall()
    return [EvModelOut(model_id=r["model_id"], provider=r["provider"],
                       model_name=r["model_name"], weekly_rate=float(r["weekly_rate"]))
            for r in rows]


@router.get("/export")
def export_ev_units(status: Optional[str] = None,
                    _: dict = Depends(get_current_user)):
    """EV units as a styled .xlsx download."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT u.ev_id, u.status, u.notes, m.provider, m.model_name, m.weekly_rate, "
            "       a.handover_date, a.rent_charged_through, a.person_id, "
            "       p.display_name AS current_rider_name, "
            "       (SELECT rider_id FROM rider_master WHERE person_id=a.person_id LIMIT 1) AS rider_id, "
            "       (SELECT GROUP_CONCAT(DISTINCT rm.hub) FROM rider_master rm "
            "          WHERE rm.person_id=a.person_id AND rm.hub IS NOT NULL AND rm.hub<>'') AS hub "
            "FROM ev_units u "
            "JOIN ev_models m ON m.model_id = u.model_id "
            "LEFT JOIN ev_assignments a ON a.ev_id = u.ev_id AND a.returned_date IS NULL "
            "LEFT JOIN person_registry p ON p.person_id = a.person_id "
            "ORDER BY u.ev_id"
        ).fetchall()
    headers = ["EV ID", "Provider", "Model", "Weekly Rate", "Status",
               "Current Rider", "Hub", "Person ID", "Rider ID", "Handover Date",
               "Rent Through", "Notes"]
    out = [
        (r["ev_id"], r["provider"], r["model_name"], float(r["weekly_rate"]),
         r["status"], r["current_rider_name"] or "", r["hub"] or "", r["person_id"] or "",
         r["rider_id"] or "", r["handover_date"] or "",
         r["rent_charged_through"] or "", r["notes"] or "")
        for r in rows if not status or r["status"] == status
    ]
    return xlsx_response(
        filename_stem="ev_units", sheet_name="EVS",
        headers=headers, rows=out,
        numeric_cols=(4,), totals_cols=(4,),
        money_cols=(4,),
        left_align_cols=(6, 11),
    )


@router.get("", response_model=list[EvUnitOut])
def list_ev_units(status: Optional[str] = None,
                  _: dict = Depends(get_current_user)) -> list[EvUnitOut]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT u.ev_id, u.status, u.notes, m.provider, m.model_name, m.weekly_rate, "
            "       a.handover_date, a.rent_charged_through, a.person_id, "
            "       p.display_name AS current_rider_name, "
            "       (SELECT rider_id FROM rider_master WHERE person_id=a.person_id LIMIT 1) AS rider_id, "
            "       (SELECT GROUP_CONCAT(DISTINCT rm.hub) FROM rider_master rm "
            "          WHERE rm.person_id=a.person_id AND rm.hub IS NOT NULL AND rm.hub<>'') AS hub "
            "FROM ev_units u "
            "JOIN ev_models m ON m.model_id = u.model_id "
            "LEFT JOIN ev_assignments a ON a.ev_id = u.ev_id AND a.returned_date IS NULL "
            "LEFT JOIN person_registry p ON p.person_id = a.person_id "
            "ORDER BY u.ev_id"
        ).fetchall()
    out: list[EvUnitOut] = []
    for r in rows:
        if status and r["status"] != status:
            continue
        out.append(EvUnitOut(
            ev_id=r["ev_id"], provider=r["provider"], model=r["model_name"],
            weekly_rate=float(r["weekly_rate"]), status=r["status"], notes=r["notes"],
            current_rider_id=r["rider_id"], current_person_id=r["person_id"],
            current_rider_name=r["current_rider_name"], hub=r["hub"],
            handover_date=r["handover_date"], rent_charged_through=r["rent_charged_through"],
        ))
    return out


@router.post("", response_model=EvUnitOut, status_code=201)
def create_ev_unit(body: EvUnitIn, _: dict = Depends(require_admin)) -> EvUnitOut:
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM ev_units WHERE ev_id=?", (body.ev_id,)).fetchone():
            raise HTTPException(409, "EV already exists")
        m = conn.execute(
            "SELECT model_id, weekly_rate FROM ev_models "
            "WHERE LOWER(provider)=LOWER(?) AND LOWER(model_name)=LOWER(?)",
            (body.provider, body.model)).fetchone()
        if not m:
            raise HTTPException(400, f"Unknown provider/model: {body.provider}/{body.model}")
        conn.execute("INSERT INTO ev_units (ev_id, model_id, status, notes) VALUES (?,?, 'spare', ?)",
                     (body.ev_id, m["model_id"], body.notes))
        conn.commit()
    return EvUnitOut(
        ev_id=body.ev_id, provider=body.provider, model=body.model,
        weekly_rate=float(m["weekly_rate"]), status="spare", notes=body.notes,
    )


@router.post("/assign")
def assign_ev(body: EvAssignIn, _: dict = Depends(require_admin)) -> dict:
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM ev_units WHERE ev_id=?", (body.ev_id,)).fetchone():
            raise HTTPException(404, "EV not found")
        rm = conn.execute("SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
                          (body.rider_id, body.company)).fetchone()
        if not rm:
            raise HTTPException(404, "Rider not found")
        pid = rm["person_id"]
        if conn.execute("SELECT 1 FROM ev_assignments WHERE person_id=? AND returned_date IS NULL",
                        (pid,)).fetchone():
            raise HTTPException(409, "Person already has an open EV assignment")
        if conn.execute("SELECT 1 FROM ev_assignments WHERE ev_id=? AND returned_date IS NULL",
                        (body.ev_id,)).fetchone():
            raise HTTPException(409, "EV already assigned to someone else")
        hod = body.handover_date.isoformat() if body.handover_date else None
        conn.execute("INSERT INTO ev_assignments (person_id, ev_id, handover_date) VALUES (?,?,?)",
                     (pid, body.ev_id, hod))
        conn.execute("UPDATE ev_units SET status='in_use' WHERE ev_id=?", (body.ev_id,))
        # If there's a stale open maintenance window for this EV, close it
        # to handover_date - 1. The new rider clearly has the EV from
        # handover_date onward, so any "still in maintenance" record is
        # wrong and would silently zero their rent.
        if hod:
            conn.execute(
                "UPDATE ev_maintenance "
                "SET to_date = date(?, '-1 day') "
                "WHERE ev_id=? AND to_date IS NULL "
                "  AND from_date <= date(?, '-1 day')",
                (hod, body.ev_id, hod),
            )
        conn.commit()
    return {"assigned": True, "person_id": pid, "ev_id": body.ev_id, "handover_date": hod}


@router.post("/return")
def return_ev(body: EvReturnIn, _: dict = Depends(require_admin)) -> dict:
    """Return an EV.

    Accept either an explicit ``ev_id`` (preferred — unambiguous) or a
    (rider_id, company) pair. If both are given they must point at the same
    open assignment.
    """
    today = (body.returned_date or date.today()).isoformat()
    if not body.ev_id and not (body.rider_id and body.company):
        raise HTTPException(400, "Provide ev_id, or (rider_id + company)")
    with get_connection() as conn:
        if body.ev_id:
            a = conn.execute(
                "SELECT assignment_id, ev_id, person_id FROM ev_assignments "
                "WHERE ev_id=? AND returned_date IS NULL", (body.ev_id,)).fetchone()
            if not a:
                raise HTTPException(404, f"No open assignment for EV {body.ev_id!r}")
            # If rider_id+company also given, sanity-check the match.
            if body.rider_id and body.company:
                rm = conn.execute(
                    "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
                    (body.rider_id, body.company)).fetchone()
                if not rm or rm["person_id"] != a["person_id"]:
                    raise HTTPException(
                        409, f"EV {body.ev_id} is not currently with rider "
                             f"{body.rider_id}@{body.company}")
        else:
            rm = conn.execute(
                "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
                (body.rider_id, body.company)).fetchone()
            if not rm:
                raise HTTPException(404, "Rider not found")
            a = conn.execute(
                "SELECT assignment_id, ev_id, person_id FROM ev_assignments "
                "WHERE person_id=? AND returned_date IS NULL",
                (rm["person_id"],)).fetchone()
            if not a:
                raise HTTPException(404, "No open EV assignment for this person")
        conn.execute("UPDATE ev_assignments SET returned_date=? WHERE assignment_id=?",
                     (today, a["assignment_id"]))
        conn.execute("UPDATE ev_units SET status='returned' WHERE ev_id=?", (a["ev_id"],))
        # Auto-close any open maintenance window on this EV. An EV being
        # returned to the depot means it isn't in maintenance anymore — and
        # if it really is, the operator can reopen a fresh window. Leaving
        # a stale to_date=NULL row around would zero the next rider's rent
        # entirely (resolve_rent treats open maintenance as blocking through
        # cycle_end).
        conn.execute(
            "UPDATE ev_maintenance SET to_date=? "
            "WHERE ev_id=? AND to_date IS NULL "
            "  AND from_date <= ?",
            (today, a["ev_id"], today),
        )
        conn.commit()
    return {"returned": True, "ev_id": a["ev_id"], "person_id": a["person_id"],
            "returned_date": today}


@router.get("/maintenance", response_model=list[MaintenanceOut])
def list_maintenance(ev_id: Optional[str] = None,
                     _: dict = Depends(get_current_user)) -> list[MaintenanceOut]:
    where, params = "", ()
    if ev_id:
        where = "WHERE ev_id=?"; params = (ev_id,)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id, ev_id, from_date, to_date, reason, created_by, created_at "
            f"FROM ev_maintenance {where} ORDER BY from_date DESC", params).fetchall()
    return [MaintenanceOut(**dict(r)) for r in rows]


@router.post("/maintenance", response_model=MaintenanceOut, status_code=201)
def add_maintenance(body: MaintenanceIn,
                    user: dict = Depends(require_admin)) -> MaintenanceOut:
    """Log an EV in maintenance. ``to_date`` is optional — leave it blank if
    you don't know when it'll come back, and close the window later with
    PATCH /evs/maintenance/{id}."""
    if body.to_date and body.to_date < body.from_date:
        raise HTTPException(400, "to_date must be on or after from_date")
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM ev_units WHERE ev_id=?", (body.ev_id,)).fetchone():
            raise HTTPException(404, "EV not found")
        # If we have a definite to_date use the existing helper; otherwise insert
        # directly so we can store NULL.
        if body.to_date:
            log_maintenance(conn, body.ev_id, body.from_date, body.to_date,
                            body.reason or "", user["email"])
        else:
            conn.execute(
                "INSERT INTO ev_maintenance (ev_id, from_date, to_date, reason, created_by) "
                "VALUES (?,?,NULL,?,?)",
                (body.ev_id, body.from_date.isoformat(),
                 body.reason or "", user["email"]),
            )
        # Flip the EV's status so the dashboard reflects it immediately.
        conn.execute("UPDATE ev_units SET status='maintenance' WHERE ev_id=?", (body.ev_id,))
        row_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.commit()
        row = conn.execute(
            "SELECT id, ev_id, from_date, to_date, reason, created_by, created_at "
            "FROM ev_maintenance WHERE id=?", (row_id,)).fetchone()
    return MaintenanceOut(**dict(row))


@router.patch("/maintenance/{maint_id}", response_model=MaintenanceOut)
def close_maintenance(maint_id: int, body: MaintenanceClose,
                      _: dict = Depends(require_admin)) -> MaintenanceOut:
    """Close an open maintenance window. If ``to_date`` is omitted, defaults
    to today."""
    close_to = (body.to_date or date.today()).isoformat()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id, ev_id, from_date FROM ev_maintenance WHERE id=?", (maint_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Maintenance row not found")
        if close_to < row["from_date"]:
            raise HTTPException(400, "to_date cannot be before from_date")
        conn.execute(
            "UPDATE ev_maintenance SET to_date=? WHERE id=?", (close_to, maint_id),
        )
        # If no other open maintenance for this EV, return the unit to in_use
        # (when held) or spare.
        still_open = conn.execute(
            "SELECT 1 FROM ev_maintenance WHERE ev_id=? AND to_date IS NULL",
            (row["ev_id"],),
        ).fetchone()
        if not still_open:
            held = conn.execute(
                "SELECT 1 FROM ev_assignments WHERE ev_id=? AND returned_date IS NULL",
                (row["ev_id"],),
            ).fetchone()
            conn.execute(
                "UPDATE ev_units SET status=? WHERE ev_id=?",
                ('in_use' if held else 'spare', row["ev_id"]),
            )
        conn.commit()
        out = conn.execute(
            "SELECT id, ev_id, from_date, to_date, reason, created_by, created_at "
            "FROM ev_maintenance WHERE id=?", (maint_id,)).fetchone()
    return MaintenanceOut(**dict(out))


@router.get("/{ev_id}/profile")
def ev_profile(ev_id: str, _: dict = Depends(get_current_user)) -> dict:
    """Full profile for a single EV: unit, current assignment, history,
    open & past maintenance windows."""
    with get_connection() as conn:
        unit = conn.execute(
            "SELECT u.ev_id, u.status, u.notes, m.provider, m.model_name, m.weekly_rate "
            "FROM ev_units u JOIN ev_models m ON m.model_id = u.model_id "
            "WHERE u.ev_id = ?", (ev_id,)).fetchone()
        if not unit:
            raise HTTPException(404, "EV not found")
        assignments = conn.execute(
            "SELECT a.assignment_id, a.person_id, p.display_name, "
            "       a.handover_date, a.returned_date, a.rent_charged_through "
            "FROM ev_assignments a "
            "LEFT JOIN person_registry p ON p.person_id = a.person_id "
            "WHERE a.ev_id = ? "
            "ORDER BY COALESCE(a.handover_date, a.created_at) DESC", (ev_id,),
        ).fetchall()
        maint = conn.execute(
            "SELECT id, from_date, to_date, reason, created_by, created_at "
            "FROM ev_maintenance WHERE ev_id = ? ORDER BY from_date DESC", (ev_id,),
        ).fetchall()
    return {
        "unit": dict(unit),
        "current": next((dict(a) for a in assignments if a["returned_date"] is None), None),
        "assignments": [dict(a) for a in assignments],
        "maintenance": [dict(m) for m in maint],
    }
