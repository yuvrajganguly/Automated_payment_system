"""RENT_DUE — the weekly rent charge for riders no payout will ever cover.

A rider owes rent for holding a vehicle, not for working, so a Zomato or
Elastic holder owes the same seven days as a Jiffy holder. The difference is
that nothing ever runs for him: no file, no cycle, no absent-rider pass, so
until September 2026 his week simply did not exist in ``transactions`` while
the provider's cost for the same days landed in ``ev_daily_ledger``.

``scan_rent_due`` lists, for one week, every open assignment held by a
direct-pay person (``payment_model.person_is_direct_pay``) with days in that
week nothing accounts for. ``book_rent_due`` writes each as a RENT_DUE row
to EV arrears — arrears, because that is what it is: owed, not deducted —
stamps the day-rows ``due`` and moves the meter, so the same days cannot be
booked twice and a cycle that turns up later (a company that starts paying
through us) bills nothing twice either. Cash receipts then recover it
through the ordinary manual rent-payment path, arrears first.

One week at a time, on purpose: the office decided on 2026-09-04 to waive the
historic gaps, and a sweep that reached back would quietly bill them.
"""

from __future__ import annotations

from datetime import date, timedelta

from payout.domain.payment_model import person_is_direct_pay
from payout.domain.rent import _day_accounted, rent_for_days

STATUS = "due"


def _d(s):
    return date.fromisoformat(str(s)[:10]) if s else None


def week_bounds(week_end) -> tuple[date, date]:
    end = _d(week_end)
    return end - timedelta(days=6), end


def last_week_end(today=None) -> date:
    """The most recent completed Sunday (weeks run Monday..Sunday, as the
    provider bills them)."""
    today = today or date.today()
    return today - timedelta(days=today.weekday() + 1)


def scan_rent_due(conn, week_end, *, today=None) -> list[dict]:
    """One entry per direct-pay holder with unaccounted days in the week:
    ``{person_id, name, ev_id, rider_id, company, hub, mob_no, weekly_rate,
    day_from, day_to, days, amount, arrears_outstanding, already_booked}``."""
    start, end = week_bounds(week_end)
    today = today or date.today()
    end = min(end, today)
    rows = conn.execute(
        "SELECT a.assignment_id, a.person_id, a.ev_id, a.handover_date, a.returned_date, "
        "       a.rent_charged_through, m.weekly_rate, pr.display_name, "
        "       pr.deduction_company, pr.deduction_rider_id "
        "FROM ev_assignments a "
        "JOIN ev_units u ON u.ev_id = a.ev_id "
        "JOIN ev_models m ON m.model_id = u.model_id "
        "JOIN person_registry pr ON pr.person_id = a.person_id "
        "WHERE (a.returned_date IS NULL OR a.returned_date >= ?) "
        "  AND COALESCE(a.handover_date, substr(a.created_at, 1, 10)) < ? "
        "ORDER BY pr.display_name, a.ev_id",
        (start.isoformat(), end.isoformat()),
    ).fetchall()
    out = []
    for a in rows:
        pid = int(a["person_id"])
        if not person_is_direct_pay(conn, pid):
            continue
        handover = _d(a["handover_date"])
        meter = _d(a["rent_charged_through"])
        first = start
        if handover and handover + timedelta(days=1) > first:
            first = handover + timedelta(days=1)  # handover day is free
        if meter and meter + timedelta(days=1) > first:
            first = meter + timedelta(days=1)
        last = end
        ret = _d(a["returned_date"])
        if ret and ret - timedelta(days=1) < last:
            last = ret - timedelta(days=1)  # return day is free
        # Already booked this week? Then the entry is the booking itself —
        # the collection sheet is printed *after* booking, so the days being
        # accounted for must not make the rider vanish from it.
        booked = conn.execute(
            "SELECT id, amount, days FROM transactions WHERE person_id=? AND event_type='RENT_DUE' "
            "AND cycle_start=? AND cycle_end=? AND remarks LIKE ?",
            (pid, start.isoformat(), week_bounds(week_end)[1].isoformat(), f"%{a['ev_id']}%"),
        ).fetchone()
        days: list[date] = []
        if booked:
            got = conn.execute(
                "SELECT MIN(day) AS d0, MAX(day) AS d1 FROM ev_daily_ledger "
                "WHERE cycle_event_id=? AND billing_status=?",
                (booked["id"], STATUS),
            ).fetchone()
            d0, d1 = _d(got["d0"]), _d(got["d1"])
            if d0 and d1:
                day = d0
                while day <= d1:
                    days.append(day)
                    day += timedelta(days=1)
        elif first <= last:
            day = first
            while day <= last:
                if not _day_accounted(conn, pid, a["ev_id"], day):
                    days.append(day)
                day += timedelta(days=1)
        if not days:
            continue
        rid = conn.execute(
            "SELECT rm.rider_id, rm.company, rm.hub, rm.mob_no FROM rider_master rm "
            "WHERE rm.person_id=? AND COALESCE(rm.is_active,1)=1 "
            "ORDER BY CASE WHEN rm.rider_id=? THEN 0 ELSE 1 END, rm.rider_id LIMIT 1",
            (pid, a["deduction_rider_id"] or ""),
        ).fetchone()
        arr = conn.execute(
            "SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)
        ).fetchone()
        n = len(days)
        out.append(
            {
                "person_id": pid,
                "name": a["display_name"],
                "ev_id": a["ev_id"],
                "rider_id": rid["rider_id"] if rid else (a["deduction_rider_id"] or ""),
                "company": rid["company"] if rid else (a["deduction_company"] or ""),
                "hub": rid["hub"] if rid else None,
                "mob_no": rid["mob_no"] if rid else None,
                "weekly_rate": int(a["weekly_rate"]),
                "day_from": days[0].isoformat(),
                "day_to": days[-1].isoformat(),
                "days": int(booked["days"]) if booked and booked["days"] else n,
                "amount": (
                    -int(booked["amount"]) if booked else rent_for_days(int(a["weekly_rate"]), n)
                ),
                "arrears_outstanding": int(arr["outstanding"]) if arr else 0,
                "already_booked": bool(booked),
            }
        )
    return out


def book_rent_due(conn, week_end, *, created_by: str, today=None) -> list[dict]:
    """Book every entry ``scan_rent_due`` returns that is not booked yet.
    Returns the entries booked, each with ``transaction_id``."""
    from payout.domain.arrears import record_rent_due
    from payout.domain.ev_daily import _upsert_row
    from payout.domain.rent import advance_rent_charged_through

    start, end = week_bounds(week_end)
    booked = []
    for e in scan_rent_due(conn, week_end, today=today):
        if e["already_booked"]:
            continue
        txn_id = record_rent_due(
            conn,
            e["person_id"],
            e["amount"],
            start,
            end,
            rider_id=e["rider_id"],
            company=e["company"],
            created_by=created_by,
            days=e["days"],
            remarks=f"EV rent due {e['day_from']}..{e['day_to']} on {e['ev_id']} "
            f"({e['days']} days; direct-pay rider, collect in cash)",
        )
        daily = round(e["weekly_rate"] / 7)
        prov = conn.execute(
            "SELECT COALESCE(m.provider_rate, m.weekly_rate) AS r FROM ev_units u "
            "JOIN ev_models m ON m.model_id = u.model_id WHERE u.ev_id=?",
            (e["ev_id"],),
        ).fetchone()
        provider_daily = round(int(prov["r"]) / 7) if prov else daily
        day = _d(e["day_from"])
        while day <= _d(e["day_to"]):
            _upsert_row(
                conn,
                ev_id=e["ev_id"],
                day=day,
                state="billable",
                person_id=e["person_id"],
                daily_cost=daily,
                provider_cost=provider_daily,
                billing_status=STATUS,
                cycle_event_id=txn_id,
            )
            day += timedelta(days=1)
        advance_rent_charged_through(conn, e["person_id"], e["day_to"])
        booked.append({**e, "transaction_id": txn_id, "already_booked": True})
    return booked
