"""Backdated-handover back-rent → EV arrears (manual flow).

When an EV is assigned with a past handover date, the days the rider held it
before the current cycle were never billed (the engine no longer catches up —
see rent.chargeable_window). Those owed days are captured here as a one-time
EV-arrears entry, on operator confirmation.
"""
from __future__ import annotations

from datetime import date, timedelta

from payout.domain.rent import (advance_rent_charged_through,
                                 maintenance_days_in_window)
from payout.money import prorate


def _open_assignment(conn, person_id):
    return conn.execute(
        "SELECT a.assignment_id, a.ev_id, a.handover_date, a.rent_charged_through, "
        "       m.weekly_rate "
        "FROM ev_assignments a "
        "JOIN ev_units u ON u.ev_id = a.ev_id "
        "JOIN ev_models m ON m.model_id = u.model_id "
        "WHERE a.person_id = ? AND a.returned_date IS NULL", (person_id,)).fetchone()


def latest_cycle_end_for(conn, person_id):
    """Most recent completed cycle_end across the rider's companies, or None."""
    r = conn.execute(
        "SELECT MAX(cc.cycle_end) AS mx FROM company_cycles cc "
        "JOIN rider_master rm ON rm.company = cc.company "
        "WHERE rm.person_id = ?", (person_id,)).fetchone()
    return r["mx"] if r and r["mx"] else None


def compute_backrent(conn, person_id, cutoff):
    """Un-billed back-rent for the open assignment, from the meter/handover up to
    ``cutoff`` (inclusive), minus maintenance. Returns None if not applicable."""
    a = _open_assignment(conn, person_id)
    if not a:
        return None
    anchor = a["rent_charged_through"] or a["handover_date"]
    if not anchor:
        return None
    start = date.fromisoformat(anchor) + timedelta(days=1)
    end = date.fromisoformat(cutoff)
    if start > end:
        return {"ev_id": a["ev_id"], "handover": a["handover_date"], "from": None,
                "to": cutoff, "days": 0, "amount": 0, "weekly_rate": int(a["weekly_rate"])}
    maint = maintenance_days_in_window(conn, a["ev_id"], start, end)
    days = max(0, (end - start).days + 1 - maint)
    return {
        "ev_id": a["ev_id"], "handover": a["handover_date"],
        "from": start.isoformat(), "to": cutoff, "days": days,
        "amount": prorate(int(a["weekly_rate"]), days),
        "weekly_rate": int(a["weekly_rate"]),
    }


def apply_backrent(conn, person_id, cutoff, created_by, amount_override=None):
    """Post the back-rent to EV arrears and advance the meter to ``cutoff``.
    ``amount_override`` (paise) lets the operator waive part of it."""
    from payout.domain.arrears import record_missed_rent
    info = compute_backrent(conn, person_id, cutoff)
    if not info or info["days"] <= 0:
        return {"added": 0}
    amount = amount_override if amount_override is not None else info["amount"]
    if amount <= 0:
        return {"added": 0}
    pr = conn.execute(
        "SELECT deduction_company, deduction_rider_id FROM person_registry "
        "WHERE person_id=?", (person_id,)).fetchone()
    record_missed_rent(
        conn, person_id, amount,
        date.fromisoformat(info["from"]), date.fromisoformat(info["to"]),
        rider_id=(pr["deduction_rider_id"] if pr else "") or "",
        company=(pr["deduction_company"] if pr else "") or "",
        created_by=created_by, days=info["days"],
        remarks=f"Back-rent for backdated handover ({info['handover']} → {cutoff})",
    )
    advance_rent_charged_through(conn, person_id, cutoff)
    return {"added": amount, "from": info["from"], "to": cutoff, "days": info["days"]}
