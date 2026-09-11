"""EV models, units, assignments and maintenance."""

from __future__ import annotations

import contextlib
from datetime import date

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response

from payout.api.auth import get_current_user, no_recruiter, require_admin, require_recruiter
from payout.api.ratelimit import rate_limit
from payout.api.routes.hubs import zone_scope
from payout.api.schemas import (
    BackrentIn,
    EvAmendReturnIn,
    EvAssignIn,
    EvCloseoutIn,
    EvCloseoutReportIn,
    EvModelOut,
    EvReturnIn,
    EvUnitIn,
    EvUnitOut,
    ExportSelection,
    MaintenanceClose,
    MaintenanceIn,
    MaintenanceOut,
)
from payout.db import get_connection
from payout.documents import ALLOWED_CONTENT_TYPES, get_storage, make_staff_key
from payout.domain.activity import record_activity
from payout.domain.adjustments import log_maintenance
from payout.domain.backrent import apply_backrent, compute_backrent, latest_cycle_end_for
from payout.domain.closeout import (
    CloseoutError,
    apply_closeout,
    mark_pending,
    pending_closeouts,
    report_for,
    save_report,
)
from payout.domain.return_heal import heal_backdated_return
from payout.exports import xlsx_response
from payout.money import to_paise

router = APIRouter()

# The dash of a scratched scooter, shrunk by the app before it is sent.
MAX_CLOSEOUT_PHOTO_BYTES = 8 * 1024 * 1024


@router.get("/models", response_model=list[EvModelOut])
def list_ev_models(_: dict = Depends(get_current_user)) -> list[EvModelOut]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT model_id, provider, model_name, weekly_rate FROM ev_models "
            "ORDER BY provider, model_name"
        ).fetchall()
    return [
        EvModelOut(
            model_id=r["model_id"],
            provider=r["provider"],
            model_name=r["model_name"],
            weekly_rate=float(r["weekly_rate"]),
        )
        for r in rows
    ]


@router.post("/export")
def export_ev_units(
    status: str | None = None,
    body: ExportSelection = Body(default=ExportSelection()),
    _: dict = Depends(no_recruiter),  # no bulk data leaves with field staff
):
    """EV units as a styled .xlsx download."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT u.ev_id, u.status, u.notes, m.provider, m.model_name, m.weekly_rate, "
            "       a.handover_date, a.rent_charged_through, a.person_id, "
            "       p.display_name AS current_rider_name, "
            "       (SELECT rider_id FROM rider_master WHERE person_id=a.person_id LIMIT 1) AS rider_id, "  # noqa: E501
            "       (SELECT GROUP_CONCAT(DISTINCT rm.hub) FROM rider_master rm "
            "          WHERE rm.person_id=a.person_id AND rm.hub IS NOT NULL AND rm.hub<>'') AS hub "  # noqa: E501
            "FROM ev_units u "
            "JOIN ev_models m ON m.model_id = u.model_id "
            "LEFT JOIN ev_assignments a ON a.ev_id = u.ev_id AND a.returned_date IS NULL "
            "LEFT JOIN person_registry p ON p.person_id = a.person_id "
            "ORDER BY u.ev_id"
        ).fetchall()
    headers = [
        "EV ID",
        "Provider",
        "Model",
        "Weekly Rate",
        "Status",
        "Current Rider",
        "Hub",
        "Person ID",
        "Rider ID",
        "Handover Date",
        "Rent Through",
        "Notes",
    ]
    out = [
        (
            r["ev_id"],
            r["provider"],
            r["model_name"],
            float(r["weekly_rate"]),
            r["status"],
            r["current_rider_name"] or "",
            r["hub"] or "",
            r["person_id"] or "",
            r["rider_id"] or "",
            r["handover_date"] or "",
            r["rent_charged_through"] or "",
            r["notes"] or "",
        )
        for r in rows
        if (not status or r["status"] == status)
        and (body.ids is None or str(r["ev_id"]) in {str(x) for x in body.ids})
    ]
    return xlsx_response(
        filename_stem="ev_units",
        sheet_name="EVS",
        headers=headers,
        rows=out,
        numeric_cols=(4,),
        totals_cols=(4,),
        money_cols=(4,),
        left_align_cols=(6, 11),
    )


@router.get("", response_model=list[EvUnitOut])
def list_ev_units(
    status: str | None = None,
    zone: str | None = None,
    mine: bool = False,
    user: dict = Depends(get_current_user),
) -> list[EvUnitOut]:
    """Fleet list. ``zone`` (North | South | unassigned) goes by the holder's
    hub; ``mine`` keeps units held by riders the caller onboarded. Both only
    make sense for units in someone's hands — spare units have no hub."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT u.ev_id, u.status, u.notes, m.provider, m.model_name, m.weekly_rate, "
            "       a.handover_date, a.rent_charged_through, a.person_id, "
            "       p.display_name AS current_rider_name, "
            "       (SELECT rider_id FROM rider_master WHERE person_id=a.person_id LIMIT 1) AS rider_id, "  # noqa: E501
            "       (SELECT GROUP_CONCAT(DISTINCT rm.hub) FROM rider_master rm "
            "          WHERE rm.person_id=a.person_id AND rm.hub IS NOT NULL AND rm.hub<>'') AS hub, "  # noqa: E501
            "       COALESCE((SELECT hz.zone FROM rider_master rm "
            "                   JOIN company_hubs hz ON hz.company=rm.company AND hz.hub=rm.hub "
            "                   WHERE rm.person_id=a.person_id AND hz.zone IS NOT NULL LIMIT 1), "
            "                (SELECT ru.zone FROM rider_master rm JOIN users ru ON ru.email=rm.recruited_by "  # noqa: E501
            "                   WHERE rm.person_id=a.person_id AND ru.zone IS NOT NULL LIMIT 1)) AS zone, "  # noqa: E501
            "       (SELECT GROUP_CONCAT(DISTINCT rm.recruited_by) FROM rider_master rm "
            "          WHERE rm.person_id=a.person_id AND rm.recruited_by IS NOT NULL) AS recruited_by, "  # noqa: E501
            "       (SELECT COUNT(*) FROM rider_master rm WHERE rm.person_id=a.person_id "
            "          AND rm.is_active=1) AS holder_active_ids, "
            "       (COALESCE((SELECT ea.outstanding FROM ev_arrears ea WHERE ea.person_id=a.person_id), 0) "  # noqa: E501
            "        + CASE WHEN COALESCE((SELECT b.current_balance FROM balances b "
            "                              WHERE b.person_id=a.person_id), 0) < 0 "
            "               THEN -(SELECT b.current_balance FROM balances b WHERE b.person_id=a.person_id) "  # noqa: E501
            "               ELSE 0 END) AS total_dues "
            "FROM ev_units u "
            "JOIN ev_models m ON m.model_id = u.model_id "
            "LEFT JOIN ev_assignments a ON a.ev_id = u.ev_id AND a.returned_date IS NULL "
            "LEFT JOIN person_registry p ON p.person_id = a.person_id "
            "ORDER BY u.ev_id"
        ).fetchall()
    z = zone_scope(user, zone) or ""
    out: list[EvUnitOut] = []
    for r in rows:
        if status and r["status"] != status:
            continue
        if z == "unassigned" and (r["person_id"] is None or r["zone"]):
            continue
        if z and z != "unassigned" and (r["zone"] or "").lower() != z:
            continue
        if mine and user["email"] not in (r["recruited_by"] or "").split(","):
            continue
        out.append(
            EvUnitOut(
                ev_id=r["ev_id"],
                provider=r["provider"],
                model=r["model_name"],
                weekly_rate=float(r["weekly_rate"]),
                status=r["status"],
                notes=r["notes"],
                current_rider_id=r["rider_id"],
                current_person_id=r["person_id"],
                current_rider_name=r["current_rider_name"],
                hub=r["hub"],
                zone=r["zone"],
                recruited_by=r["recruited_by"],
                holder_active=(int(r["holder_active_ids"] or 0) > 0) if r["person_id"] else None,
                total_dues=int(r["total_dues"] or 0) if r["person_id"] else None,
                handover_date=r["handover_date"],
                rent_charged_through=r["rent_charged_through"],
            )
        )
    return out


@router.post("", response_model=EvUnitOut, status_code=201)
def create_ev_unit(body: EvUnitIn, user: dict = Depends(require_recruiter)) -> EvUnitOut:
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM ev_units WHERE ev_id=?", (body.ev_id,)).fetchone():
            raise HTTPException(409, "EV already exists")
        m = conn.execute(
            "SELECT model_id, weekly_rate FROM ev_models "
            "WHERE LOWER(provider)=LOWER(?) AND LOWER(model_name)=LOWER(?)",
            (body.provider, body.model),
        ).fetchone()
        if not m:
            raise HTTPException(400, f"Unknown provider/model: {body.provider}/{body.model}")
        conn.execute(
            "INSERT INTO ev_units (ev_id, model_id, status, notes) VALUES (?,?, 'spare', ?)",
            (body.ev_id, m["model_id"], body.notes),
        )
        status_ = "spare"
        current_person_id = None
        handover = None
        if body.person_id is not None:
            # Hand the new unit straight to its rider — one transaction, so a
            # bad person id leaves no orphan spare behind.
            if not conn.execute(
                "SELECT 1 FROM person_registry WHERE person_id=?", (body.person_id,)
            ).fetchone():
                raise HTTPException(404, f"Person {body.person_id} not found")
            handover = _open_assignment(
                conn, body.ev_id, body.person_id, body.handover_date, user["email"]
            )
            status_, current_person_id = "in_use", body.person_id
        record_activity(
            conn,
            user,
            "ev.create",
            entity_type="ev",
            entity_id=body.ev_id,
            label=f"{body.provider} {body.model}",
            person_id=current_person_id,
            details={"assigned_to": current_person_id, "handover_date": handover},
        )
        conn.commit()
    return EvUnitOut(
        ev_id=body.ev_id,
        provider=body.provider,
        model=body.model,
        weekly_rate=float(m["weekly_rate"]),
        status=status_,
        notes=body.notes,
        current_person_id=current_person_id,
        handover_date=handover,
    )


def _open_assignment(
    conn, ev_id: str, pid: int, handover_date: date | None, by: str | None = None
) -> str | None:
    """Open an ev_assignments row for (person, EV) and mark the unit in_use.
    Refuses when either side already has an open assignment."""
    if conn.execute(
        "SELECT 1 FROM ev_assignments WHERE person_id=? AND returned_date IS NULL", (pid,)
    ).fetchone():
        raise HTTPException(409, "Person already has an open EV assignment")
    if conn.execute(
        "SELECT 1 FROM ev_assignments WHERE ev_id=? AND returned_date IS NULL", (ev_id,)
    ).fetchone():
        raise HTTPException(409, "EV already assigned to someone else")
    # Never NULL. A blank handover date used to be stored as-is, and rent then
    # had nothing to date the assignment against: the leg billed every cycle in
    # full, at its own rate, including cycles that closed before the vehicle
    # left the office. Today is the only defensible default at the moment
    # somebody taps "hand over".
    hod = (handover_date or date.today()).isoformat()
    conn.execute(
        "INSERT INTO ev_assignments (person_id, ev_id, handover_date, assigned_by) "
        "VALUES (?,?,?,?)",
        (pid, ev_id, hod, by),
    )
    conn.execute("UPDATE ev_units SET status='in_use' WHERE ev_id=?", (ev_id,))
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
            (hod, ev_id, hod),
        )
    return hod


@router.post("/assign")
def assign_ev(body: EvAssignIn, user: dict = Depends(require_recruiter)) -> dict:
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM ev_units WHERE ev_id=?", (body.ev_id,)).fetchone():
            raise HTTPException(404, "EV not found")
        if body.person_id is not None:
            if not conn.execute(
                "SELECT 1 FROM person_registry WHERE person_id=?", (body.person_id,)
            ).fetchone():
                raise HTTPException(404, f"Person {body.person_id} not found")
            pid = body.person_id
        elif body.rider_id and body.company:
            rm = conn.execute(
                "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
                (body.rider_id, body.company),
            ).fetchone()
            if not rm:
                raise HTTPException(404, "Rider not found")
            pid = rm["person_id"]
        else:
            raise HTTPException(400, "Provide person_id, or (rider_id + company)")
        hod = _open_assignment(conn, body.ev_id, pid, body.handover_date, user["email"])
        record_activity(
            conn,
            user,
            "ev.assign",
            entity_type="ev",
            entity_id=body.ev_id,
            person_id=pid,
            details={"handover_date": hod, "rider_id": body.rider_id, "company": body.company},
        )
        conn.commit()
    return {"assigned": True, "person_id": pid, "ev_id": body.ev_id, "handover_date": hod}


def _find_open_assignment(conn, body: EvReturnIn):
    """Locate the open assignment for body.ev_id or (rider_id, company).

    Returns the assignment row, or None when an ``ev_id`` was given but the unit
    has no open assignment (i.e. it is a spare). Raises for bad input: no
    selector, unknown rider, a rider with no open assignment, or an ev_id that
    doesn't match the named rider.
    """
    if not body.ev_id and not (body.rider_id and body.company):
        raise HTTPException(400, "Provide ev_id, or (rider_id + company)")
    if body.ev_id:
        a = conn.execute(
            "SELECT assignment_id, ev_id, person_id FROM ev_assignments "
            "WHERE ev_id=? AND returned_date IS NULL",
            (body.ev_id,),
        ).fetchone()
        if a and body.rider_id and body.company:
            rm = conn.execute(
                "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
                (body.rider_id, body.company),
            ).fetchone()
            if not rm or rm["person_id"] != a["person_id"]:
                raise HTTPException(
                    409,
                    f"EV {body.ev_id} is not currently with rider {body.rider_id}@{body.company}",
                )
        return a
    rm = conn.execute(
        "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
        (body.rider_id, body.company),
    ).fetchone()
    if not rm:
        raise HTTPException(404, "Rider not found")
    a = conn.execute(
        "SELECT assignment_id, ev_id, person_id FROM ev_assignments "
        "WHERE person_id=? AND returned_date IS NULL",
        (rm["person_id"],),
    ).fetchone()
    if not a:
        raise HTTPException(404, "No open EV assignment for this person")
    return a


def _close_open_maintenance(conn, ev_id: str, today: str) -> None:
    """Close any open maintenance window on an EV (a returned/spared unit isn't
    in maintenance; a stale open window would zero the next rider's rent)."""
    conn.execute(
        "UPDATE ev_maintenance SET to_date=? WHERE ev_id=? AND to_date IS NULL AND from_date <= ?",
        (today, ev_id, today),
    )


@router.post("/return")
def return_ev(body: EvReturnIn, user: dict = Depends(require_recruiter)) -> dict:
    """Return an EV to the provider (retire it) - whether it is currently with a
    rider OR sitting as a spare.

      * With a rider: closes the open assignment (rent stops) and marks the unit
        'returned'.
      * Spare (no open assignment): just marks the unit 'returned'.

    Accepts an explicit ``ev_id`` (preferred, unambiguous) or a
    (rider_id, company) pair.
    """
    today = (body.returned_date or date.today()).isoformat()
    heal = None
    closeout = None
    with get_connection() as conn:
        a = _find_open_assignment(conn, body)
        if a:
            ev_id, person_id = a["ev_id"], a["person_id"]
            conn.execute(
                "UPDATE ev_assignments SET returned_date=?, returned_by=? WHERE assignment_id=?",
                (today, user["email"], a["assignment_id"]),
            )
            # Backdated? Reverse every rent charge for days the rider no
            # longer had the EV (see payout/domain/return_heal.py).
            heal = heal_backdated_return(
                conn,
                assignment_id=a["assignment_id"],
                retire=True,
                created_by=user["email"],
            )
            # EV closed -> the admin now answers what happened to the security
            # deposit (POST /evs/closeouts/{assignment_id}); until then the
            # assignment is closeout_pending and the web keeps asking.
            mark_pending(conn, a["assignment_id"])
            closeout = _closeout_prompt(conn, a["assignment_id"])
        else:
            # Spare: no open assignment. The unit itself must exist.
            ev_id, person_id = body.ev_id, None
            if not conn.execute("SELECT 1 FROM ev_units WHERE ev_id=?", (ev_id,)).fetchone():
                raise HTTPException(404, f"EV {ev_id!r} not found")
        conn.execute("UPDATE ev_units SET status='returned' WHERE ev_id=?", (ev_id,))
        _close_open_maintenance(conn, ev_id, today)
        record_activity(
            conn,
            user,
            "ev.return",
            entity_type="ev",
            entity_id=ev_id,
            person_id=person_id,
            details={
                "returned_date": today,
                "from_rider": person_id is not None,
                "heal": {k: v for k, v in (heal or {}).items() if k != "events"},
            },
        )
        conn.commit()
    out = {"returned": True, "ev_id": ev_id, "person_id": person_id, "returned_date": today}
    if heal:
        out["heal"] = heal
    if closeout:
        out["closeout"] = closeout
    return out


@router.post("/to-spare")
def mark_spare(body: EvReturnIn, user: dict = Depends(require_recruiter)) -> dict:
    """Take an EV back from its rider and keep it as a SPARE (available for
    reassignment) instead of retiring it.

    Ends the current assignment so rent stops, and sets the unit status to
    'spare'. Accepts an explicit ``ev_id`` or a (rider_id, company) pair.

    An EV that was RETURNED (retired) by mistake, or that the provider sent
    back, can be brought back into the pool the same way: with no rider to
    take it from, the unit simply becomes 'spare' again (the reverse of
    /return on a spare).
    """
    today = (body.returned_date or date.today()).isoformat()
    with get_connection() as conn:
        a = _find_open_assignment(conn, body)
        if not a:
            unit = conn.execute(
                "SELECT status FROM ev_units WHERE ev_id=?", (body.ev_id,)
            ).fetchone()
            if not unit:
                raise HTTPException(404, f"EV {body.ev_id!r} not found")
            if unit["status"] == "spare":
                raise HTTPException(409, f"EV {body.ev_id!r} is already spare.")
            conn.execute("UPDATE ev_units SET status='spare' WHERE ev_id=?", (body.ev_id,))
            record_activity(
                conn,
                user,
                "ev.spare",
                entity_type="ev",
                entity_id=body.ev_id,
                details={"previous_status": unit["status"], "as_of": today},
            )
            conn.commit()
            return {
                "spare": True,
                "ev_id": body.ev_id,
                "person_id": None,
                "as_of": today,
                "previous_status": unit["status"],
                "heal": None,
            }
        conn.execute(
            "UPDATE ev_assignments SET returned_date=?, returned_by=? WHERE assignment_id=?",
            (today, user["email"], a["assignment_id"]),
        )
        heal = heal_backdated_return(
            conn,
            assignment_id=a["assignment_id"],
            retire=False,
            created_by=user["email"],
        )
        mark_pending(conn, a["assignment_id"])
        closeout = _closeout_prompt(conn, a["assignment_id"])
        conn.execute("UPDATE ev_units SET status='spare' WHERE ev_id=?", (a["ev_id"],))
        _close_open_maintenance(conn, a["ev_id"], today)
        record_activity(
            conn,
            user,
            "ev.spare",
            entity_type="ev",
            entity_id=a["ev_id"],
            person_id=a["person_id"],
            details={
                "as_of": today,
                "from_rider": True,
                "heal": {k: v for k, v in (heal or {}).items() if k != "events"},
            },
        )
        conn.commit()
    return {
        "spare": True,
        "ev_id": a["ev_id"],
        "person_id": a["person_id"],
        "as_of": today,
        "heal": heal,
        "closeout": closeout,
    }


def _closeout_prompt(conn, assignment_id: int) -> dict | None:
    """The just-closed assignment as the close-out form needs it."""
    return next((p for p in pending_closeouts(conn) if p["assignment_id"] == assignment_id), None)


@router.get("/closeouts")
def list_closeouts(
    pending: bool = True,
    ev_id: str | None = None,
    _: dict = Depends(require_admin),
) -> list[dict]:
    """Closed assignments still waiting for the deposit answer (``pending``,
    default), or the recorded close-outs (``pending=false``, optionally for
    one unit)."""
    with get_connection() as conn:
        if pending:
            return pending_closeouts(conn)
        where, params = [], []
        if ev_id:
            where.append("c.ev_id=?")
            params.append(ev_id)
        rows = conn.execute(
            "SELECT c.*, pr.display_name AS name, a.handover_date, a.returned_date "
            "FROM ev_closeouts c JOIN person_registry pr ON pr.person_id=c.person_id "
            "JOIN ev_assignments a ON a.assignment_id=c.assignment_id "
            + (("WHERE " + " AND ".join(where)) if where else "")
            + " ORDER BY c.created_at DESC, c.assignment_id DESC LIMIT 500",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


@router.post("/closeouts/{assignment_id}")
def close_out(assignment_id: int, body: EvCloseoutIn, user: dict = Depends(require_admin)) -> dict:
    """Answer the deposit question for a closed assignment. Money moves here:
    rent cleared from the deposit, damage recorded, leftover credited to the
    next payout (or refunded in cash), excess charges added to dues."""
    with get_connection() as conn:
        try:
            out = apply_closeout(
                conn,
                assignment_id,
                sd_returned=body.sd_returned,
                sd_amount=None if body.sd_amount is None else to_paise(body.sd_amount),
                damage_charges=to_paise(body.damage_charges or 0),
                rent_charges=None if body.rent_charges is None else to_paise(body.rent_charges),
                credit_next_payout=body.credit_next_payout,
                note=body.note,
                created_by=user["email"],
            )
        except CloseoutError as exc:
            raise HTTPException(400, str(exc)) from exc
        record_activity(
            conn,
            user,
            "ev.closeout",
            entity_type="ev",
            entity_id=out["ev_id"],
            person_id=out["person_id"],
            details={k: v for k, v in out.items() if k not in ("ev_id", "person_id")},
        )
        conn.commit()
    return out


@router.get("/closeouts/mine")
def my_closeout_reports(
    limit: int = 50,
    user: dict = Depends(require_recruiter),
) -> list[dict]:
    """Assignments I closed that still need the deposit question answered, plus
    what I have already reported. This is the recruiter's side of the
    close-out: the office settles it, but the prompt belongs to whoever took
    the vehicle back."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT a.assignment_id, a.ev_id, a.person_id, a.handover_date, a.returned_date, "
            "       pr.display_name AS name, m.model_name AS model, m.provider "
            "FROM ev_assignments a "
            "JOIN person_registry pr ON pr.person_id = a.person_id "
            "LEFT JOIN ev_units u ON u.ev_id = a.ev_id "
            "LEFT JOIN ev_models m ON m.model_id = u.model_id "
            "WHERE a.closeout_pending = 1 AND a.returned_by = ? "
            "ORDER BY a.returned_date DESC, a.assignment_id DESC LIMIT ?",
            (user["email"], min(max(limit, 1), 200)),
        ).fetchall()
        return [{**dict(r), "report": report_for(conn, int(r["assignment_id"]))} for r in rows]


@router.post("/closeouts/{assignment_id}/report")
def report_closeout(
    assignment_id: int,
    body: EvCloseoutReportIn,
    user: dict = Depends(require_recruiter),
) -> dict:
    """Record what the vehicle came back like: whether the security deposit
    went back to the rider in cash, and if it did not, the damage.

    No money moves here — this writes an observation, and the office's
    close-out (``POST /evs/closeouts/{id}``) remains the only route that
    settles the deposit against arrears and dues. Re-reporting corrects the
    previous answer; once the office has settled, it is refused.
    """
    with get_connection() as conn:
        try:
            out = save_report(
                conn,
                assignment_id,
                sd_returned=body.sd_returned,
                damage_charges=to_paise(body.damage_charges or 0),
                damage_note=body.damage_note,
                reported_by=user["email"],
            )
        except CloseoutError as exc:
            raise HTTPException(400, str(exc)) from exc
        record_activity(
            conn,
            user,
            "ev.closeout_report",
            entity_type="ev",
            entity_id=out["ev_id"],
            person_id=out["person_id"],
            details={
                "sd_returned": out["sd_returned"],
                "damage_charges": out["damage_charges"],
                "note": out["damage_note"],
            },
        )
        conn.commit()
    return out


@router.post("/closeouts/{assignment_id}/photo")
def upload_closeout_photo(
    assignment_id: int,
    file: UploadFile = File(...),
    user: dict = Depends(require_recruiter),
    _: None = Depends(rate_limit("staff-photo", 40, 3600)),
) -> dict:
    """The damage, photographed. Hangs off a report that already exists.

    Same ordering as everywhere else in the app: the report saves first and
    the picture follows, so a failed upload on a hub's signal costs the photo
    and not the assessment. The image is the evidence behind a charge somebody
    will dispute, so it is kept even after the office settles — unlike the
    report itself, which is frozen at that point.
    """
    ctype = (file.content_type or "").split(";")[0].strip().lower()
    if ctype not in ALLOWED_CONTENT_TYPES or ctype == "application/pdf":
        raise HTTPException(415, "Send a JPEG, PNG or WebP image")
    data = file.file.read(MAX_CLOSEOUT_PHOTO_BYTES + 1)
    if not data:
        raise HTTPException(400, "The file was empty")
    if len(data) > MAX_CLOSEOUT_PHOTO_BYTES:
        raise HTTPException(413, "That image is too large — the app should shrink it first")

    with get_connection() as conn:
        row = conn.execute(
            "SELECT photo_key FROM ev_closeout_reports WHERE assignment_id=?", (assignment_id,)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Record what the vehicle came back like first")
        key = make_staff_key(user["email"], "ev_damage", ctype)
        get_storage().put(key, data, ctype)
        conn.execute(
            "UPDATE ev_closeout_reports SET photo_key=? WHERE assignment_id=?",
            (key, assignment_id),
        )
        conn.commit()
        old = row["photo_key"]
    if old and old != key:
        with contextlib.suppress(Exception):
            get_storage().delete(old)
    return {"ok": True}


@router.get("/closeouts/{assignment_id}/photo")
def closeout_photo(assignment_id: int, user: dict = Depends(get_current_user)) -> Response:
    """The damage photo behind a deposit charge. Any signed-in member of staff:
    the office has to see what it is being asked to charge for, and the
    recruiter has to be able to check what they sent."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT photo_key FROM ev_closeout_reports WHERE assignment_id=?", (assignment_id,)
        ).fetchone()
    if not row or not row["photo_key"]:
        raise HTTPException(404, "No photo")
    try:
        data = get_storage().get(row["photo_key"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, "No photo") from exc
    ext = row["photo_key"].rsplit(".", 1)[-1]
    ctype = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    return Response(
        content=data, media_type=ctype, headers={"Cache-Control": "private, max-age=300"}
    )


@router.post("/close")
def close_ev(body: EvReturnIn, _: dict = Depends(require_recruiter)) -> dict:
    """Deprecated alias for /return, which now retires spares as well. Kept so
    older clients / the existing 'Close' button keep working."""
    return return_ev(body, _)


_DISMISS_KINDS = ("absent", "sponsored", "other")
_REFLAG_AFTER_CYCLES = 4  # an 'absent' dismissal resurfaces after this many more missed cycles


@router.get("/suspected-returns")
def suspected_returns(
    min_cycles: int = 2,
    include_dismissed: bool = False,
    _: dict = Depends(get_current_user),
) -> list[dict]:
    """EV holders who look like they've returned the vehicle without telling
    anyone: an open assignment, but no payout for ``min_cycles``+ cycles while
    rent kept falling to arrears.

    ``suggested_return_date`` is the first missed cycle's start — recording the
    return with that date reverses the entire missed streak (the return day
    itself is free).

    An operator who knows better can dismiss a row (POST
    /suspected-returns/dismiss): the rider is genuinely absent, or the EV is
    sponsored and its rent written off. Dismissed rows are hidden; a
    'sponsored' dismissal is permanent, any other kind resurfaces once the
    missed streak has grown by ``_REFLAG_AFTER_CYCLES`` more cycles (marked
    ``reflagged``). ``include_dismissed=1`` lists them all with the dismissal.
    """
    out: list[dict] = []
    with get_connection() as conn:
        holders = conn.execute(
            "SELECT a.assignment_id, a.ev_id, a.handover_date, pr.person_id, pr.display_name, "
            "       pr.deduction_company AS company, pr.deduction_rider_id AS rider_id, "
            "       m.model_name AS model, m.weekly_rate, "
            "       COALESCE(ea.outstanding, 0) AS arrears_outstanding, "
            "       d.kind AS dismiss_kind, d.reason AS dismiss_reason, "
            "       d.missed_cycles_then, d.dismissed_by, d.dismissed_at "
            "FROM ev_assignments a "
            "JOIN person_registry pr ON pr.person_id = a.person_id "
            "JOIN ev_units u  ON u.ev_id = a.ev_id "
            "JOIN ev_models m ON m.model_id = u.model_id "
            "LEFT JOIN ev_arrears ea ON ea.person_id = pr.person_id "
            "LEFT JOIN suspected_return_dismissals d ON d.assignment_id = a.assignment_id "
            "WHERE a.returned_date IS NULL"
        ).fetchall()
        for h in holders:
            pid = h["person_id"]
            last_payout = conn.execute(
                "SELECT MAX(cycle_end) AS m FROM transactions "
                "WHERE person_id=? AND event_type='PAYOUT'",
                (pid,),
            ).fetchone()["m"]
            streak = conn.execute(
                "SELECT COUNT(*) AS n, MIN(cycle_start) AS since, "
                "       COALESCE(SUM(-amount), 0) AS missed_amount "
                "FROM transactions WHERE person_id=? AND event_type='RENT_MISSED' "
                "AND cycle_start > ?",
                (pid, last_payout or "0000-00-00"),
            ).fetchone()
            if (streak["n"] or 0) < min_cycles:
                continue
            dismissed = None
            if h["dismiss_kind"]:
                grown = int(streak["n"] or 0) - int(h["missed_cycles_then"] or 0)
                reflagged = h["dismiss_kind"] != "sponsored" and grown >= _REFLAG_AFTER_CYCLES
                dismissed = {
                    "kind": h["dismiss_kind"],
                    "reason": h["dismiss_reason"],
                    "by": h["dismissed_by"],
                    "at": h["dismissed_at"],
                    "missed_cycles_then": h["missed_cycles_then"],
                    "reflagged": reflagged,
                }
                if not reflagged and not include_dismissed:
                    continue
            out.append(
                {
                    "assignment_id": h["assignment_id"],
                    "dismissed": dismissed,
                    "person_id": pid,
                    "display_name": h["display_name"],
                    "rider_id": h["rider_id"],
                    "company": h["company"],
                    "ev_id": h["ev_id"],
                    "model": h["model"],
                    "weekly_rate": h["weekly_rate"],
                    "last_payout_end": last_payout,
                    "missed_cycles": streak["n"],
                    "missed_since": streak["since"],
                    "missed_amount": streak["missed_amount"],
                    "arrears_outstanding": h["arrears_outstanding"],
                    "suggested_return_date": streak["since"],
                }
            )
    out.sort(key=lambda r: (-(r["missed_cycles"] or 0), -(r["missed_amount"] or 0)))
    return out


@router.post("/suspected-returns/dismiss")
def dismiss_suspected_return(
    payload: dict = Body(...), user: dict = Depends(require_admin)
) -> dict:
    """The rider still holds the EV — stop suggesting a return.

    Body: {"ev_id": str, "kind": "absent" | "sponsored" | "other", "reason": str}
    Rent keeps accruing exactly as before; only the suggestion goes away
    (see suspected_returns for when it comes back)."""
    ev_id = (payload.get("ev_id") or "").strip()
    kind = (payload.get("kind") or "").strip().lower()
    reason = (payload.get("reason") or "").strip()
    if kind not in _DISMISS_KINDS:
        raise HTTPException(400, f"kind must be one of {', '.join(_DISMISS_KINDS)}")
    if not reason:
        raise HTTPException(400, "A reason is required.")
    with get_connection() as conn:
        a = conn.execute(
            "SELECT a.assignment_id, a.person_id, pr.display_name FROM ev_assignments a "
            "JOIN person_registry pr ON pr.person_id = a.person_id "
            "WHERE a.ev_id=? AND a.returned_date IS NULL",
            (ev_id,),
        ).fetchone()
        if not a:
            raise HTTPException(404, "No open assignment for that EV.")
        last_payout = conn.execute(
            "SELECT MAX(cycle_end) AS m FROM transactions "
            "WHERE person_id=? AND event_type='PAYOUT'",
            (a["person_id"],),
        ).fetchone()["m"]
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM transactions WHERE person_id=? AND event_type='RENT_MISSED' "
            "AND cycle_start > ?",
            (a["person_id"], last_payout or "0000-00-00"),
        ).fetchone()["n"]
        conn.execute(
            "DELETE FROM suspected_return_dismissals WHERE assignment_id=?", (a["assignment_id"],)
        )
        conn.execute(
            "INSERT INTO suspected_return_dismissals "
            "(assignment_id, kind, reason, missed_cycles_then, dismissed_by) VALUES (?,?,?,?,?)",
            (a["assignment_id"], kind, reason, int(n or 0), user["email"]),
        )
        record_activity(
            conn,
            user,
            "ev.suspected_return.dismiss",
            entity_type="ev",
            entity_id=ev_id,
            label=a["display_name"],
            person_id=a["person_id"],
            details={"kind": kind, "reason": reason, "missed_cycles": int(n or 0)},
        )
        conn.commit()
    return {"ev_id": ev_id, "assignment_id": a["assignment_id"], "kind": kind, "dismissed": True}


@router.post("/suspected-returns/undismiss")
def undismiss_suspected_return(
    payload: dict = Body(...), user: dict = Depends(require_admin)
) -> dict:
    """Put a dismissed EV back on the suspected-returns list."""
    ev_id = (payload.get("ev_id") or "").strip()
    with get_connection() as conn:
        a = conn.execute(
            "SELECT assignment_id, person_id FROM ev_assignments WHERE ev_id=? "
            "AND returned_date IS NULL",
            (ev_id,),
        ).fetchone()
        if not a:
            raise HTTPException(404, "No open assignment for that EV.")
        n = conn.execute(
            "DELETE FROM suspected_return_dismissals WHERE assignment_id=?", (a["assignment_id"],)
        ).rowcount
        record_activity(
            conn,
            user,
            "ev.suspected_return.undismiss",
            entity_type="ev",
            entity_id=ev_id,
            person_id=a["person_id"],
        )
        conn.commit()
    return {"ev_id": ev_id, "dismissed": False, "removed": int(n or 0)}


@router.post("/amend-return")
def amend_return(body: EvAmendReturnIn, user: dict = Depends(require_admin)) -> dict:
    """Move an already-recorded return to an EARLIER date and heal the books.

    For the common ops mistake: the EV actually went back on the 3rd, but
    nobody clicked Return until the 12th (or clicked it with today's date).
    Only backdating is allowed — pushing a return *later* would mean charging
    rent again, which is a deliberate act, not a correction.
    """
    new_ret = body.returned_date.isoformat()
    with get_connection() as conn:
        a = conn.execute(
            "SELECT assignment_id, person_id, returned_date, handover_date "
            "FROM ev_assignments WHERE ev_id=? AND returned_date IS NOT NULL "
            "ORDER BY returned_date DESC LIMIT 1",
            (body.ev_id,),
        ).fetchone()
        if not a:
            raise HTTPException(404, f"EV {body.ev_id!r} has no recorded return to amend")
        if new_ret >= str(a["returned_date"]):
            raise HTTPException(
                400,
                f"Return is recorded as {a['returned_date']}; the amended date must be "
                "earlier. To charge rent again, re-assign the EV instead.",
            )
        if a["handover_date"] and new_ret < str(a["handover_date"]):
            raise HTTPException(400, "Return date can't be before the handover date")
        u = conn.execute("SELECT status FROM ev_units WHERE ev_id=?", (body.ev_id,)).fetchone()
        conn.execute(
            "UPDATE ev_assignments SET returned_date=? WHERE assignment_id=?",
            (new_ret, a["assignment_id"]),
        )
        heal = heal_backdated_return(
            conn,
            assignment_id=a["assignment_id"],
            retire=(u is not None and u["status"] == "returned"),
            created_by=user["email"],
        )
        # The amend may free NEW debt below the deposit line; the deposit was
        # already applied once at the original return, so do NOT re-apply.
        #
        # This is the one EV action that never reached the activity feed —
        # ``ev.amend_return`` was listed in ACTIONS but nothing wrote it, so a
        # correction that moves money left no trace on the rider's timeline.
        record_activity(
            conn,
            user,
            "ev.amend_return",
            entity_type="ev",
            entity_id=body.ev_id,
            person_id=a["person_id"],
            details={
                "from": a["returned_date"],
                "to": new_ret,
                "refunded_paise": (heal or {}).get("refunded"),
                "days_reversed": (heal or {}).get("days_reversed"),
            },
        )
        conn.commit()
    return {
        "amended": True,
        "ev_id": body.ev_id,
        "person_id": a["person_id"],
        "previous_date": a["returned_date"],
        "returned_date": new_ret,
        "heal": heal,
    }


@router.get("/{ev_id}/backrent")
def backrent_suggestion(ev_id: str, _: dict = Depends(get_current_user)) -> dict:
    """Soft suggestion: un-billed back-rent for a backdated handover on the EV's
    current rider. Nothing is written."""
    with get_connection() as conn:
        a = conn.execute(
            "SELECT person_id FROM ev_assignments WHERE ev_id=? AND returned_date IS NULL", (ev_id,)
        ).fetchone()
        if not a:
            return {"applicable": False}
        cutoff = latest_cycle_end_for(conn, a["person_id"]) or date.today().isoformat()
        info = compute_backrent(conn, a["person_id"], cutoff)
    if not info or info["days"] <= 0:
        return {"applicable": False}
    return {
        "applicable": True,
        "ev_id": info["ev_id"],
        "handover": info["handover"],
        "from": info["from"],
        "to": info["to"],
        "days": info["days"],
        "amount": info["amount"],
        "weekly_rate": info["weekly_rate"],
    }


@router.post("/backrent")
def apply_backrent_ep(body: BackrentIn, user: dict = Depends(require_admin)) -> dict:
    """Post the backdated back-rent to EV arrears (operator-confirmed). Optional
    ``amount`` (rupees) waives part of it."""
    with get_connection() as conn:
        a = conn.execute(
            "SELECT person_id FROM ev_assignments WHERE ev_id=? AND returned_date IS NULL",
            (body.ev_id,),
        ).fetchone()
        if not a:
            raise HTTPException(404, f"No open assignment for EV {body.ev_id!r}")
        cutoff = latest_cycle_end_for(conn, a["person_id"]) or date.today().isoformat()
        amt = to_paise(body.amount) if body.amount is not None else None
        res = apply_backrent(conn, a["person_id"], cutoff, user["email"], amount_override=amt)
        conn.commit()
    return res


@router.get("/maintenance", response_model=list[MaintenanceOut])
def list_maintenance(
    ev_id: str | None = None, _: dict = Depends(get_current_user)
) -> list[MaintenanceOut]:
    where, params = "", ()
    if ev_id:
        where = "WHERE ev_id=?"
        params = (ev_id,)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT id, ev_id, from_date, to_date, reason, created_by, created_at "
            f"FROM ev_maintenance {where} ORDER BY from_date DESC",
            params,
        ).fetchall()
    return [MaintenanceOut(**dict(r)) for r in rows]


@router.post("/maintenance", response_model=MaintenanceOut, status_code=201)
def add_maintenance(body: MaintenanceIn, user: dict = Depends(require_recruiter)) -> MaintenanceOut:
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
            log_maintenance(
                conn, body.ev_id, body.from_date, body.to_date, body.reason or "", user["email"]
            )
        else:
            conn.execute(
                "INSERT INTO ev_maintenance (ev_id, from_date, to_date, reason, created_by) "
                "VALUES (?,?,NULL,?,?)",
                (body.ev_id, body.from_date.isoformat(), body.reason or "", user["email"]),
            )
        # Flip the EV's status so the dashboard reflects it immediately.
        conn.execute("UPDATE ev_units SET status='maintenance' WHERE ev_id=?", (body.ev_id,))
        row_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        record_activity(
            conn,
            user,
            "ev.maintenance_open",
            entity_type="ev",
            entity_id=body.ev_id,
            details={
                "maintenance_id": row_id,
                "from_date": body.from_date.isoformat(),
                "to_date": body.to_date.isoformat() if body.to_date else None,
                "reason": body.reason,
            },
        )
        conn.commit()
        row = conn.execute(
            "SELECT id, ev_id, from_date, to_date, reason, created_by, created_at "
            "FROM ev_maintenance WHERE id=?",
            (row_id,),
        ).fetchone()
    return MaintenanceOut(**dict(row))


@router.patch("/maintenance/{maint_id}", response_model=MaintenanceOut)
def close_maintenance(
    maint_id: int, body: MaintenanceClose, user: dict = Depends(require_recruiter)
) -> MaintenanceOut:
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
            "UPDATE ev_maintenance SET to_date=? WHERE id=?",
            (close_to, maint_id),
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
                ("in_use" if held else "spare", row["ev_id"]),
            )
        record_activity(
            conn,
            user,
            "ev.maintenance_close",
            entity_type="ev",
            entity_id=row["ev_id"],
            details={"maintenance_id": maint_id, "to_date": close_to},
        )
        conn.commit()
        out = conn.execute(
            "SELECT id, ev_id, from_date, to_date, reason, created_by, created_at "
            "FROM ev_maintenance WHERE id=?",
            (maint_id,),
        ).fetchone()
    return MaintenanceOut(**dict(out))


@router.get("/{ev_id}/profile")
def ev_profile(ev_id: str, _: dict = Depends(get_current_user)) -> dict:
    """Full profile for a single EV: unit, current assignment, history,
    open & past maintenance windows."""
    with get_connection() as conn:
        unit = conn.execute(
            "SELECT u.ev_id, u.status, u.notes, m.provider, m.model_name, m.weekly_rate "
            "FROM ev_units u JOIN ev_models m ON m.model_id = u.model_id "
            "WHERE u.ev_id = ?",
            (ev_id,),
        ).fetchone()
        if not unit:
            raise HTTPException(404, "EV not found")
        assignments = conn.execute(
            "SELECT a.assignment_id, a.person_id, p.display_name, "
            "       a.handover_date, a.returned_date, a.rent_charged_through "
            "FROM ev_assignments a "
            "LEFT JOIN person_registry p ON p.person_id = a.person_id "
            "WHERE a.ev_id = ? "
            "ORDER BY COALESCE(a.handover_date, a.created_at) DESC",
            (ev_id,),
        ).fetchall()
        maint = conn.execute(
            "SELECT id, from_date, to_date, reason, created_by, created_at "
            "FROM ev_maintenance WHERE ev_id = ? ORDER BY from_date DESC",
            (ev_id,),
        ).fetchall()
    return {
        "unit": dict(unit),
        "current": next((dict(a) for a in assignments if a["returned_date"] is None), None),
        "assignments": [dict(a) for a in assignments],
        "maintenance": [dict(m) for m in maint],
    }
