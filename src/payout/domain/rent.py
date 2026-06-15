"""EV rent calculation.

Rent is a continuous daily meter. Each cycle it is billed from the day after
`rent_charged_through` (the last date already billed) up to the cycle end - so
gaps are caught up, overlaps and re-runs never double-charge, and the meter
advances whether a day was charged (rider present) or missed to arrears (absent).

Pure helpers (chargeable_window, chargeable_days, rent_for_days) plus resolve_rent
which reads the assignment + rate and applies maintenance windows and manual
overrides (waive_days, waive_all, rent_override). advance_rent_charged_through
moves the meter forward after the engine commits a cycle.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta

from payout.config import STANDARD_CYCLE_DAYS


@dataclass
class RentInfo:
    has_ev: bool
    ev_id: str | None
    provider: str | None
    model: str | None
    weekly_rate: float
    handover_date: date | None
    days: int
    rent: float
    base_days: int = 0
    maintenance_days: int = 0
    waived_days: int = 0
    rent_from: date | None = None
    charged_through: date | None = None


def chargeable_window(cycle_start, cycle_end, handover_date, charged_through=None):
    """Inclusive (start, end) range to bill, or None if zero days.

    Once rent has been billed, billing resumes the day after `charged_through`
    (catching any gap). On a brand-new assignment, the day after handover (or the
    cycle start for a legacy rider with no handover). None if nothing is due.
    """
    if charged_through is not None:
        start = charged_through + timedelta(days=1)
    elif handover_date is not None and handover_date > cycle_start:
        start = handover_date + timedelta(days=1)
    else:
        start = cycle_start
    if start > cycle_end:
        return None
    return (start, cycle_end)


def chargeable_days(cycle_start, cycle_end, handover_date, charged_through=None):
    window = chargeable_window(cycle_start, cycle_end, handover_date, charged_through)
    return 0 if window is None else (window[1] - window[0]).days + 1


def rent_for_days(weekly_rate, days):
    if days <= 0:
        return 0.0
    if days == STANDARD_CYCLE_DAYS:
        return float(weekly_rate)
    return weekly_rate / 7.0 * days


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


def resolve_rent(conn, person_id, cycle_start, cycle_end, *,
                 waive_days=0, waive_all=False, rent_override=None):
    row = conn.execute(
        """
        SELECT a.ev_id, a.handover_date, a.rent_charged_through,
               m.provider, m.model_name, m.weekly_rate
        FROM ev_assignments a
        JOIN ev_units  u ON u.ev_id = a.ev_id
        JOIN ev_models m ON m.model_id = u.model_id
        WHERE a.person_id = ? AND a.returned_date IS NULL
        """,
        (person_id,),
    ).fetchone()
    if not row:
        return RentInfo(False, None, None, None, 0.0, None, 0, 0.0)

    hod = date.fromisoformat(row["handover_date"]) if row["handover_date"] else None
    charged = date.fromisoformat(row["rent_charged_through"]) if row["rent_charged_through"] else None
    window = chargeable_window(cycle_start, cycle_end, hod, charged)
    if window is None:
        base = maint = 0
        rent_from = None
    else:
        rent_from = window[0]
        base = (window[1] - window[0]).days + 1
        maint = maintenance_days_in_window(conn, row["ev_id"], window[0], window[1])

    effective = max(0, base - maint - max(0, waive_days))
    if rent_override is not None:
        rent = float(rent_override)
    elif waive_all:
        rent = 0.0
    else:
        rent = rent_for_days(row["weekly_rate"], effective)

    return RentInfo(
        has_ev=True, ev_id=row["ev_id"], provider=row["provider"], model=row["model_name"],
        weekly_rate=float(row["weekly_rate"]), handover_date=hod, days=effective, rent=rent,
        base_days=base, maintenance_days=maint, waived_days=max(0, waive_days),
        rent_from=rent_from, charged_through=charged,
    )


def advance_rent_charged_through(conn, person_id, through_date):
    """Move the rent meter forward (called after a cycle is charged or missed)."""
    td = through_date.isoformat() if hasattr(through_date, "isoformat") else str(through_date)
    conn.execute(
        "UPDATE ev_assignments SET rent_charged_through=? "
        "WHERE person_id=? AND returned_date IS NULL",
        (td, person_id),
    )
