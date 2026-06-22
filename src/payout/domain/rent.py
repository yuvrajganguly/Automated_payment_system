"""EV rent calculation.

Rent is a continuous daily meter. Each cycle it is billed from the day after
``rent_charged_through`` (the last date already billed) up to the cycle end —
so gaps are caught up, overlaps and re-runs never double-charge, and the meter
advances whether a day was charged (rider present) or missed to arrears (absent).

Multi-assignment handling: a rider can swap EVs mid-cycle (return one, take
another the same day). For a given (person, cycle) we sum rent across every
assignment that overlapped the cycle, with each assignment's window clamped to
``[handover_date + 1 .. returned_date - 1]`` (handover day and return day are
free). The old "look at the open assignment only" rule silently dropped the
returned EV's days.

Pure helpers (chargeable_window, chargeable_days, rent_for_days) plus
resolve_rent which sums across overlapping assignments, applies maintenance
windows and manual overrides. advance_rent_charged_through advances the meter
on every assignment that participated in a cycle.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

from payout.config import STANDARD_CYCLE_DAYS


@dataclass
class AssignmentLeg:
    """One assignment's contribution to a cycle's rent."""
    assignment_id: int
    ev_id: str
    provider: str
    model: str
    weekly_rate: float
    handover_date: date | None
    returned_date: date | None
    rent_charged_through: date | None
    days: int            # chargeable after maintenance & waiver
    base_days: int       # before maintenance / waiver
    maintenance_days: int
    rent: float
    rent_from: date | None
    rent_through: date | None


@dataclass
class RentInfo:
    has_ev: bool
    ev_id: str | None             # display: open assignment if any, else most recent returned
    provider: str | None
    model: str | None
    weekly_rate: float
    handover_date: date | None
    days: int                     # total across legs
    rent: float                   # total across legs
    base_days: int = 0
    maintenance_days: int = 0
    waived_days: int = 0
    rent_from: date | None = None
    charged_through: date | None = None
    legs: list[AssignmentLeg] = field(default_factory=list)


def chargeable_window(cycle_start, cycle_end, handover_date,
                       charged_through=None, returned_date=None):
    """Inclusive ``(start, end)`` chargeable range for a single assignment, or
    ``None`` if zero days.

    Catch-up model (per multi-company drift discussions):
      * ``start = charged_through + 1``. NO clamp to ``cycle_start`` — when
        the meter is behind (e.g. a new joiner, or a prior cycle that was
        skipped) this cycle picks up the unbilled days. The engine emits a
        warning if the resulting window exceeds 21 days, but bills it.
      * Brand-new assignment with no meter: ``handover_date + 1`` when
        handover lands mid-cycle; else ``cycle_start``.
      * Return day is free: ``end = min(cycle_end, returned_date - 1)``.
      * ``RENT_MISSED`` deliberately does NOT advance ``charged_through``, so
        any later cycle that covers the same days can still pick them up and
        flip them from 'missed' to 'recovered' in the daily ledger.
    """
    if charged_through is not None:
        start = charged_through + timedelta(days=1)
    elif handover_date is not None and handover_date >= cycle_start:
        # Handover day is free whether handover lands mid-cycle (> cycle_start)
        # OR exactly on cycle_start. Without the >= the engine would charge for
        # cycle_start while the daily ledger marks it 'handover_free', so the
        # two views disagree by one day. Aligning them keeps Provider Weekly's
        # "expected vs collected" reconciliation clean.
        start = handover_date + timedelta(days=1)
    else:
        start = cycle_start
    end = cycle_end
    if returned_date is not None:
        end = min(end, returned_date - timedelta(days=1))
    if start > end:
        return None
    return (start, end)


def chargeable_days(cycle_start, cycle_end, handover_date,
                     charged_through=None, returned_date=None):
    window = chargeable_window(cycle_start, cycle_end, handover_date,
                                charged_through, returned_date)
    return 0 if window is None else (window[1] - window[0]).days + 1


def rent_for_days(weekly_rate, days):
    """Rent for ``days`` of a weekly rate, in integer paise (rounded once)."""
    from payout.money import prorate
    return prorate(int(weekly_rate), days, STANDARD_CYCLE_DAYS)


def maintenance_days_in_window(conn, ev_id, win_start, win_end):
    """Count cycle days the EV was in maintenance.

    A row with ``to_date IS NULL`` means the EV is still in maintenance (no
    return date logged yet) — for cycle billing we treat it as blocked all
    the way through ``win_end``.
    """
    rows = conn.execute(
        "SELECT from_date, to_date FROM ev_maintenance WHERE ev_id=?", (ev_id,)
    ).fetchall()
    blocked = set()
    for r in rows:
        lo = max(date.fromisoformat(r["from_date"]), win_start)
        if r["to_date"]:
            hi = min(date.fromisoformat(r["to_date"]), win_end)
        else:
            hi = win_end
        day = lo
        while day <= hi:
            blocked.add(day)
            day += timedelta(days=1)
    return len(blocked)


def _parse_date(s):
    return date.fromisoformat(s) if s else None


def resolve_rent(conn, person_id, cycle_start, cycle_end, *,
                 waive_days=0, waive_all=False, rent_override=None):
    """Sum rent across every assignment that overlapped the cycle.

    Overlap rule: handover_date <= cycle_end AND
                  (returned_date IS NULL OR returned_date >= cycle_start)
    Each assignment's chargeable window is clamped to its handover/return
    dates and then to the cycle. Maintenance and waiver days reduce the
    chargeable count per leg uniformly.

    ``rent_override`` (when supplied) replaces the engine-computed total —
    it's a flat override, not a per-leg one. ``waive_all`` zeroes the total.
    ``waive_days`` reduces the *total* base days (applied to the longest leg
    first; if it exceeds the longest leg it spills over to the next).
    """
    rows = conn.execute(
        """
        SELECT a.assignment_id, a.ev_id, a.handover_date, a.returned_date,
               a.rent_charged_through, m.provider, m.model_name, m.weekly_rate
        FROM ev_assignments a
        JOIN ev_units  u ON u.ev_id = a.ev_id
        JOIN ev_models m ON m.model_id = u.model_id
        WHERE a.person_id = ?
          AND (a.returned_date IS NULL OR a.returned_date >= ?)
          AND (a.handover_date IS NULL OR a.handover_date <= ?)
        ORDER BY COALESCE(a.handover_date, a.created_at) ASC
        """,
        (person_id, cycle_start.isoformat() if hasattr(cycle_start, "isoformat") else str(cycle_start),
         cycle_end.isoformat() if hasattr(cycle_end, "isoformat") else str(cycle_end)),
    ).fetchall()

    if not rows:
        return RentInfo(False, None, None, None, 0.0, None, 0, 0.0)

    # Build per-leg chargeable windows.
    legs_data = []
    for r in rows:
        hod = _parse_date(r["handover_date"])
        ret = _parse_date(r["returned_date"])
        charged = _parse_date(r["rent_charged_through"])
        win = chargeable_window(cycle_start, cycle_end, hod, charged, ret)
        if win is None:
            base = maint = 0
            rfrom = rthrough = None
        else:
            rfrom, rthrough = win
            base = (rthrough - rfrom).days + 1
            maint = maintenance_days_in_window(conn, r["ev_id"], rfrom, rthrough)
        legs_data.append({
            "row": r, "hod": hod, "ret": ret, "charged": charged,
            "rent_from": rfrom, "rent_through": rthrough,
            "base": base, "maint": maint,
        })

    # Apply the waive_days budget across legs (largest leg first).
    waive_left = max(0, int(waive_days or 0))
    for leg in sorted(legs_data, key=lambda x: -x["base"]):
        eff = max(0, leg["base"] - leg["maint"])
        if waive_left <= 0:
            leg["waived"] = 0
        elif eff >= waive_left:
            leg["waived"] = waive_left
            waive_left = 0
        else:
            leg["waived"] = eff
            waive_left -= eff
    for leg in legs_data:
        leg.setdefault("waived", 0)

    built_legs: list[AssignmentLeg] = []
    total_base = total_maint = total_waived = total_days = 0
    total_rent = 0
    rent_from_overall: date | None = None
    rent_through_overall: date | None = None
    open_leg = None
    most_recent_returned = None

    for leg in legs_data:
        r = leg["row"]
        eff_days = max(0, leg["base"] - leg["maint"] - leg["waived"])
        leg_rent = rent_for_days(r["weekly_rate"], eff_days)
        built = AssignmentLeg(
            assignment_id=r["assignment_id"], ev_id=r["ev_id"],
            provider=r["provider"], model=r["model_name"],
            weekly_rate=int(r["weekly_rate"]),
            handover_date=leg["hod"], returned_date=leg["ret"],
            rent_charged_through=leg["charged"],
            days=eff_days, base_days=leg["base"],
            maintenance_days=leg["maint"], rent=leg_rent,
            rent_from=leg["rent_from"], rent_through=leg["rent_through"],
        )
        built_legs.append(built)
        total_days += eff_days
        total_base += leg["base"]
        total_maint += leg["maint"]
        total_waived += leg["waived"]
        total_rent += leg_rent
        if leg["rent_from"]:
            rent_from_overall = (leg["rent_from"] if rent_from_overall is None
                                 else min(rent_from_overall, leg["rent_from"]))
        if leg["rent_through"]:
            rent_through_overall = (leg["rent_through"] if rent_through_overall is None
                                    else max(rent_through_overall, leg["rent_through"]))
        if leg["ret"] is None and open_leg is None:
            open_leg = built
        elif leg["ret"] is not None:
            if (most_recent_returned is None
                    or (leg["ret"] and most_recent_returned.returned_date
                        and leg["ret"] > most_recent_returned.returned_date)):
                most_recent_returned = built

    # Overrides apply to the TOTAL.
    if rent_override is not None:
        total_rent = int(rent_override)
    elif waive_all:
        total_rent = 0

    display = open_leg or most_recent_returned or built_legs[0]
    return RentInfo(
        has_ev=True,
        ev_id=display.ev_id, provider=display.provider, model=display.model,
        weekly_rate=display.weekly_rate,
        handover_date=display.handover_date,
        days=total_days, rent=total_rent,
        base_days=total_base, maintenance_days=total_maint,
        waived_days=total_waived,
        rent_from=rent_from_overall,
        charged_through=rent_through_overall,
        legs=built_legs,
    )


def advance_rent_charged_through(conn, person_id, through_date):
    """Move the rent meter forward for every assignment that participated in
    the cycle. Both the open assignment (if any) AND any returned assignment
    whose meter hasn't been moved past its return date yet.
    """
    td = through_date.isoformat() if hasattr(through_date, "isoformat") else str(through_date)
    # Open assignment: meter advances to through_date.
    conn.execute(
        "UPDATE ev_assignments SET rent_charged_through=? "
        "WHERE person_id=? AND returned_date IS NULL",
        (td, person_id),
    )
    # Returned assignments: advance their meter to (returned_date - 1) — the
    # last day they could have been billed — but only when the current value
    # is earlier, so we never roll a meter backwards.
    conn.execute(
        "UPDATE ev_assignments "
        "SET rent_charged_through = date(returned_date, '-1 day') "
        "WHERE person_id=? AND returned_date IS NOT NULL "
        "  AND (rent_charged_through IS NULL "
        "       OR rent_charged_through < date(returned_date, '-1 day'))",
        (person_id,),
    )
