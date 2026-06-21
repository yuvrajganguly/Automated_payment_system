"""Day-level EV ledger — populates ``ev_daily_ledger``.

Each row in the ledger answers two questions for a single (ev_id, day):

  * What was the EV doing? (state)        billable / handover_free /
                                          return_free / maintenance / unassigned
  * What was the billing outcome?         billed / missed / recovered / pending

Rules:

  - ``provider_cost`` is always populated (weekly_rate / 7). It's what we owe
    the EV provider (Raft, Blive, etc.) that day regardless of who has the EV.
  - ``daily_cost`` is the *rider-side* expectation. Zero when nobody is supposed
    to pay (handover_free, return_free, maintenance, unassigned). Otherwise
    equal to provider_cost.
  - billing_status is set when a cycle includes this day:
        billed   — RENT event for the assigned rider covers this day (rider
                   present, RENT_COLLECTED ≥ RENT)
        missed   — RENT_MISSED event covers this day (rider absent)
        recovered — a 'missed' day that was later paid down by RENT_RECOVERED
                    or XC_RENT_RECOVERED
        pending  — billable day inside a cycle that hasn't been processed
                   yet (no RENT or RENT_MISSED event yet)
  - cycle_event_id points to the RENT / RENT_MISSED transaction id that
    produced the billing_status. recovery_event_id points to the RENT_RECOVERED
    /XC_RENT_RECOVERED that healed a missed day.

The public helpers update the ledger in place; they are idempotent (re-running
on the same cycle does not duplicate or drift).
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta


def _iter_days(start: date, end_inclusive: date):
    d = start
    while d <= end_inclusive:
        yield d
        d += timedelta(days=1)


def _parse(s):
    return date.fromisoformat(s) if s else None


def _upsert_row(conn, *, ev_id, day, state, person_id, daily_cost, provider_cost,
                billing_status=None, cycle_event_id=None, recovery_event_id=None):
    """Insert-or-overwrite a single day-row. Status fields are sticky unless
    the caller passes an explicit non-None value — this lets callers update
    just the billing fields without losing the state/cost data."""
    existing = conn.execute(
        "SELECT * FROM ev_daily_ledger WHERE ev_id=? AND day=?",
        (ev_id, day.isoformat()),
    ).fetchone()
    if existing:
        # Preserve recovery info unless caller explicitly resets it.
        new_billing = billing_status if billing_status is not None else existing["billing_status"]
        new_cycle_event = cycle_event_id if cycle_event_id is not None else existing["cycle_event_id"]
        new_recovery_event = recovery_event_id if recovery_event_id is not None else existing["recovery_event_id"]
        conn.execute(
            "UPDATE ev_daily_ledger SET "
            "  state=?, assigned_person_id=?, daily_cost=?, provider_cost=?, "
            "  billing_status=?, cycle_event_id=?, recovery_event_id=?, "
            "  last_updated=datetime('now') "
            "WHERE ev_id=? AND day=?",
            (state, person_id, daily_cost, provider_cost,
             new_billing, new_cycle_event, new_recovery_event,
             ev_id, day.isoformat()),
        )
    else:
        conn.execute(
            "INSERT INTO ev_daily_ledger "
            "(ev_id, day, state, assigned_person_id, daily_cost, provider_cost, "
            " billing_status, cycle_event_id, recovery_event_id) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (ev_id, day.isoformat(), state, person_id, daily_cost, provider_cost,
             billing_status, cycle_event_id, recovery_event_id),
        )


def materialize_cycle_for_person(
    conn, *, person_id, cycle_start, cycle_end,
    legs, billing_event_id, billing_status,
):
    """Write one day-row for every day of every leg that contributed to this
    cycle's rent for ``person_id``. State/cost are derived from the leg.
    ``billing_status`` is one of ``'billed'`` / ``'missed'`` / ``'pending'``.
    ``billing_event_id`` is the RENT (or RENT_MISSED) transaction id that
    produced the status — None for pending.

    Maintenance and handover/return overrides are applied: if a leg's window
    overlaps an ev_maintenance row, those days become ``maintenance``. The
    handover day itself becomes ``handover_free``; the day before return
    becomes ``return_free``.
    """
    cs = cycle_start if hasattr(cycle_start, "isoformat") else date.fromisoformat(cycle_start)
    ce = cycle_end if hasattr(cycle_end, "isoformat") else date.fromisoformat(cycle_end)
    for leg in legs:
        ev_id = leg.ev_id
        weekly = leg.weekly_rate
        daily = weekly / 7.0
        hod = leg.handover_date
        ret = leg.returned_date
        # The leg's contributing window inside this cycle. When None, the leg
        # has no chargeable days in this cycle — we still write the handover/
        # return overlay rows below so the calendar reflects truth, but no
        # billing_status is attributed.
        win_lo = max(cs, leg.rent_from) if leg.rent_from else None
        win_hi = min(ce, leg.rent_through) if leg.rent_through else None
        # Pre-collect maintenance days for this ev across the whole cycle so
        # we mark them properly even if outside the billable window.
        maint = []
        for m in conn.execute(
            "SELECT from_date, to_date FROM ev_maintenance WHERE ev_id=?",
            (ev_id,),
        ):
            lo = _parse(m["from_date"])
            hi = _parse(m["to_date"]) if m["to_date"] else ce
            if not lo: continue
            maint.append((max(lo, cs), min(hi, ce)))
        def in_maint(day):
            return any(lo <= day <= hi for lo, hi in maint)

        # For every day of the leg's overlap with the cycle, write a row.
        leg_lo = max(cs, hod) if hod else cs
        leg_hi = min(ce, ret) if ret else ce
        for day in _iter_days(leg_lo, leg_hi):
            state = "billable"
            this_daily = daily
            this_billing = billing_status
            this_event = billing_event_id
            if hod and day == hod:
                state = "handover_free"; this_daily = 0.0; this_billing = None; this_event = None
            elif ret and day == ret:
                state = "return_free"; this_daily = 0.0; this_billing = None; this_event = None
            elif in_maint(day):
                state = "maintenance"; this_daily = 0.0; this_billing = None; this_event = None
            elif win_lo and win_hi and (day < win_lo or day > win_hi):
                # Outside the chargeable window of this leg in this cycle
                # (e.g. already billed in a prior cycle).
                this_billing = None; this_event = None
            _upsert_row(
                conn, ev_id=ev_id, day=day, state=state,
                person_id=person_id,
                daily_cost=this_daily, provider_cost=daily,
                billing_status=this_billing,
                cycle_event_id=this_event,
            )


def materialize_unassigned_window(conn, *, ev_id, start, end_inclusive, weekly_rate):
    """Write 'unassigned' rows for an EV that wasn't held by anyone over the
    window. provider_cost is still owed (we pay the provider regardless).
    """
    daily = weekly_rate / 7.0
    for day in _iter_days(start, end_inclusive):
        _upsert_row(
            conn, ev_id=ev_id, day=day, state="unassigned",
            person_id=None, daily_cost=0.0, provider_cost=daily,
        )


def attribute_recovery(conn, *, person_id, recovery_event_id, amount,
                       daily_unit_cost_hint=None):
    """Apply a recovery (RENT_RECOVERED or XC_RENT_RECOVERED) by healing the
    oldest 'missed' days for this person. Walks forward chronologically until
    ``amount`` worth of daily_cost is recovered (or no more missed days).

    Returns the amount actually attributed. Excess is left unattributed — the
    rider's general ledger absorbs it elsewhere.
    """
    remaining = float(amount)
    healed = 0.0
    if remaining <= 0:
        return 0.0
    rows = conn.execute(
        "SELECT ev_id, day, daily_cost FROM ev_daily_ledger "
        "WHERE assigned_person_id=? AND billing_status='missed' "
        "ORDER BY day ASC",
        (person_id,),
    ).fetchall()
    for r in rows:
        cost = float(r["daily_cost"] or daily_unit_cost_hint or 0)
        if cost <= 0:
            continue
        if remaining + 0.005 < cost:
            break  # not enough left to cover even one more day
        conn.execute(
            "UPDATE ev_daily_ledger SET billing_status='recovered', "
            "  recovery_event_id=?, last_updated=datetime('now') "
            "WHERE ev_id=? AND day=?",
            (recovery_event_id, r["ev_id"], r["day"]),
        )
        remaining -= cost
        healed += cost
    return round(healed, 2)
