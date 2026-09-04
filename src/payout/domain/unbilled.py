"""Unbilled EV days — the maintenance sweep behind the 2026-09-04 fix.

Before rent.resolve_rent learnt to reach back over unaccounted days, a rider
whose cycles arrived out of order (Spencer's 15-21, Myntra 24-30, Spencer's
22-31) had the days between two cycles silently written off: the second
company's cycle pushed the meter past them and nothing ever billed them.

``scan_unbilled`` walks every assignment's held days that sit at or behind
its meter and lists the runs that neither the day-ledger nor any RENT /
RENT_MISSED window accounts for. ``apply_unbilled`` books one such run as
EV arrears (a RENT_MISSED row, so the next payout recovers it the normal
way) and stamps the day-ledger so the run cannot be reported twice.

Assignments without a meter are skipped: their owed days belong to the
back-rent flow (POST /evs/backrent), which is the operator's call.
"""

from __future__ import annotations

from datetime import date, timedelta

from payout.domain.rent import _day_accounted, rent_for_days


def _parse(s):
    return date.fromisoformat(str(s)[:10]) if s else None


def _first_evidence(conn, person_id, ev_id):
    """Earliest day the records show ``person_id`` holding ``ev_id``: a
    day-ledger row, or the start of a RENT / RENT_MISSED window."""
    led = conn.execute(
        "SELECT MIN(day) AS d FROM ev_daily_ledger WHERE ev_id=? AND assigned_person_id=?",
        (ev_id, person_id),
    ).fetchone()["d"]
    txn = conn.execute(
        "SELECT MIN(cycle_start) AS d FROM transactions WHERE person_id=? "
        "AND event_type IN ('RENT','RENT_MISSED')",
        (person_id,),
    ).fetchone()["d"]
    days = [_parse(x) for x in (led, txn) if x]
    return min(days) if days else None


def scan_unbilled(conn, *, lookback_days=120, today=None):
    """Return a list of ``{person_id, name, ev_id, assignment_id, weekly_rate,
    runs: [{from, to, days, amount}], days, amount}`` — one entry per
    assignment with at least one unaccounted run, oldest run first."""
    today = today or date.today()
    floor = today - timedelta(days=lookback_days)
    # Days before the first committed cycle were settled by the seed openings.
    go_live = conn.execute("SELECT MIN(cycle_start) AS d FROM company_cycles").fetchone()["d"]
    if go_live:
        floor = max(floor, _parse(go_live))
    rows = conn.execute(
        "SELECT a.assignment_id, a.person_id, a.ev_id, a.handover_date, a.returned_date, "
        "       a.rent_charged_through, m.weekly_rate, pr.display_name "
        "FROM ev_assignments a "
        "JOIN ev_units u ON u.ev_id = a.ev_id "
        "JOIN ev_models m ON m.model_id = u.model_id "
        "JOIN person_registry pr ON pr.person_id = a.person_id "
        "WHERE a.rent_charged_through IS NOT NULL "
        "  AND (a.returned_date IS NULL OR a.returned_date >= ?) "
        "ORDER BY a.person_id, a.assignment_id",
        (floor.isoformat(),),
    ).fetchall()
    out = []
    for a in rows:
        meter = _parse(a["rent_charged_through"])
        hod = _parse(a["handover_date"])
        ret = _parse(a["returned_date"])
        if hod is not None:
            lo = max(floor, hod + timedelta(days=1))
        else:
            # No handover date (seed-era or hastily created): only count from
            # the first day anything shows the rider held this unit. Earlier
            # days are unknown, not owed — that is the back-rent flow's call.
            first = _first_evidence(conn, a["person_id"], a["ev_id"])
            if first is None:
                continue
            lo = max(floor, first)
        hi = meter
        if ret is not None:
            hi = min(hi, ret - timedelta(days=2))  # return day and the day before are free
        if lo > hi:
            continue
        runs = []
        run_start = None
        day = lo
        while day <= hi + timedelta(days=1):
            owed = day <= hi and not _day_accounted(conn, a["person_id"], a["ev_id"], day)
            if owed and run_start is None:
                run_start = day
            elif not owed and run_start is not None:
                n = (day - run_start).days
                runs.append(
                    {
                        "from": run_start.isoformat(),
                        "to": (day - timedelta(days=1)).isoformat(),
                        "days": n,
                        "amount": rent_for_days(int(a["weekly_rate"]), n),
                    }
                )
                run_start = None
            day += timedelta(days=1)
        if runs:
            out.append(
                {
                    "assignment_id": a["assignment_id"],
                    "person_id": a["person_id"],
                    "name": a["display_name"],
                    "ev_id": a["ev_id"],
                    "weekly_rate": int(a["weekly_rate"]),
                    "handover": a["handover_date"],
                    "returned": a["returned_date"],
                    "meter": a["rent_charged_through"],
                    "runs": runs,
                    "days": sum(r["days"] for r in runs),
                    "amount": sum(r["amount"] for r in runs),
                }
            )
    return out


def apply_unbilled(conn, *, person_id, ev_id, day_from, day_to, created_by="unbilled-days"):
    """Book the run ``[day_from, day_to]`` to EV arrears and mark its
    day-rows 'missed'. Days already accounted for are refused (returns 0)."""
    from payout.domain.arrears import record_missed_rent
    from payout.domain.ev_daily import _upsert_row

    d0, d1 = _parse(day_from), _parse(day_to)
    if d0 is None or d1 is None or d0 > d1:
        return 0
    a = conn.execute(
        "SELECT a.assignment_id, m.weekly_rate FROM ev_assignments a "
        "JOIN ev_units u ON u.ev_id = a.ev_id "
        "JOIN ev_models m ON m.model_id = u.model_id "
        "WHERE a.person_id=? AND a.ev_id=? "
        "  AND (a.handover_date IS NULL OR a.handover_date < ?) "
        "  AND (a.returned_date IS NULL OR a.returned_date > ?) "
        "ORDER BY a.assignment_id DESC LIMIT 1",
        (person_id, ev_id, day_from, day_to),
    ).fetchone()
    if a is None:
        return 0
    days = []
    day = d0
    while day <= d1:
        if _day_accounted(conn, person_id, ev_id, day):
            return 0  # something billed part of it meanwhile — re-scan
        days.append(day)
        day += timedelta(days=1)
    n = len(days)
    amount = rent_for_days(int(a["weekly_rate"]), n)
    pr = conn.execute(
        "SELECT deduction_company, deduction_rider_id FROM person_registry WHERE person_id=?",
        (person_id,),
    ).fetchone()
    record_missed_rent(
        conn,
        person_id,
        amount,
        d0,
        d1,
        rider_id=(pr["deduction_rider_id"] if pr else "") or "",
        company=(pr["deduction_company"] if pr else "") or "",
        created_by=created_by,
        days=n,
        remarks=f"EV rent for unbilled days {day_from}..{day_to} ({ev_id}); "
        "days fell between two companies' cycles",
    )
    event_id = conn.execute(
        "SELECT MAX(id) AS id FROM transactions WHERE person_id=? AND event_type='RENT_MISSED'",
        (person_id,),
    ).fetchone()["id"]
    daily = round(int(a["weekly_rate"]) / 7)
    for day in days:
        _upsert_row(
            conn,
            ev_id=ev_id,
            day=day,
            state="billable",
            person_id=person_id,
            daily_cost=daily,
            provider_cost=daily,
            billing_status="missed",
            cycle_event_id=event_id,
        )
    return amount
