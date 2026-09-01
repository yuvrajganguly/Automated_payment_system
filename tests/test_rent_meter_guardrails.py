"""Guardrails from the 01-Jul-2026 manual-rent incident.

Two invariants:
  1. ``allowed_paid_through`` — a manual payment may advance the rent meter
     only as far as the money reaches (arrears money buys no new days).
  2. ``backfill_billed_days`` — days newly covered by a manual payment get
     day-ledger rows even when no cycle ever materialized them, so day-grain
     reports stop undercounting manual collections.
"""

from payout.domain.ev_daily import backfill_billed_days
from payout.domain.rent import allowed_paid_through

WEEK = 126000  # Rs.1,260/week in paise -> Rs.180/day


def test_exact_week_advances_seven_days():
    assert (
        allowed_paid_through(
            cur_through="2026-06-14",
            period_start=None,
            rent_paise=WEEK,
            weekly_rate=WEEK,
        )
        == "2026-06-21"
    )


def test_arrears_only_payment_buys_no_new_days():
    # Rs.1,250 that all went to arrears -> rent_paise=0 -> meter must not move.
    assert (
        allowed_paid_through(
            cur_through="2026-06-14",
            period_start=None,
            rent_paise=0,
            weekly_rate=WEEK,
        )
        == "2026-06-14"
    )


def test_partial_day_floors_down():
    # 6.9 days of money must not buy the 7th day.
    assert (
        allowed_paid_through(
            cur_through="2026-06-14",
            period_start=None,
            rent_paise=int(WEEK * 6.9 / 7),
            weekly_rate=WEEK,
        )
        == "2026-06-20"
    )


def test_no_meter_starts_at_period_start():
    assert (
        allowed_paid_through(
            cur_through=None,
            period_start="2026-06-01",
            rent_paise=WEEK,
            weekly_rate=WEEK,
        )
        == "2026-06-07"
    )


def test_no_meter_no_window_returns_none():
    assert (
        allowed_paid_through(
            cur_through=None,
            period_start=None,
            rent_paise=WEEK,
            weekly_rate=WEEK,
        )
        is None
    )


def _seed_assignment(db, ev="EVG1"):
    mid = db.execute("SELECT model_id FROM ev_models WHERE provider='Raft' LIMIT 1").fetchone()[0]
    db.execute("INSERT INTO ev_units (ev_id, model_id, status) VALUES (?,?,'in_use')", (ev, mid))
    pid = db.execute("INSERT INTO person_registry (display_name) VALUES ('G')").lastrowid
    db.execute(
        "INSERT INTO ev_assignments (person_id, ev_id, handover_date, "
        "rent_charged_through) VALUES (?,?,'2026-05-31','2026-06-14')",
        (pid, ev),
    )
    db.commit()
    return pid, ev


def test_backfill_creates_only_missing_rows(db):
    pid, ev = _seed_assignment(db)
    # Day 16 already exists (missed) — must be left alone.
    db.execute(
        "INSERT INTO ev_daily_ledger (ev_id, day, state, assigned_person_id, "
        "daily_cost, provider_cost, billing_status) "
        "VALUES (?,?,?,?,?,?,'missed')",
        (ev, "2026-06-16", "billable", pid, 180.0, 180.0),
    )
    created = backfill_billed_days(
        db, person_id=pid, event_id=4242, day_from="2026-06-15", day_to="2026-06-18"
    )
    db.commit()
    assert created == 3  # 15, 17, 18 — not 16
    rows = {
        r[0]: (r[1], r[2])
        for r in db.execute(
            "SELECT day, billing_status, cycle_event_id FROM ev_daily_ledger "
            "WHERE ev_id=? AND day BETWEEN '2026-06-15' AND '2026-06-18'",
            (ev,),
        )
    }
    assert rows["2026-06-15"] == ("billed", 4242)
    assert rows["2026-06-16"][0] == "missed"  # untouched
    assert rows["2026-06-17"] == ("billed", 4242)
    assert rows["2026-06-18"] == ("billed", 4242)


def test_backfill_without_open_assignment_is_noop(db):
    pid = db.execute("INSERT INTO person_registry (display_name) VALUES ('NoEV')").lastrowid
    db.commit()
    assert (
        backfill_billed_days(
            db, person_id=pid, event_id=1, day_from="2026-06-01", day_to="2026-06-07"
        )
        == 0
    )


def test_backdated_backrent_goes_to_arrears(db):
    """A backdated handover's un-billed days convert to EV arrears (not a giant
    catch-up RENT), and the meter advances so future cycles bill cleanly."""
    from payout.domain.arrears import get_arrears
    from payout.domain.backrent import apply_backrent, compute_backrent

    mid = db.execute("SELECT model_id FROM ev_models WHERE provider='Blive'").fetchone()["model_id"]
    pid = db.execute(
        "INSERT INTO person_registry (display_name, deduction_company, deduction_rider_id) "
        "VALUES ('BD','Myntra','BD1')"
    ).lastrowid
    db.execute(
        "INSERT OR IGNORE INTO ev_arrears (person_id,total_missed,total_recovered,outstanding) VALUES (?,0,0,0)",  # noqa: E501
        (pid,),
    )
    db.execute("INSERT INTO ev_units (ev_id,model_id,status) VALUES ('EVBD',?,'in_use')", (mid,))
    # handover 15 Jun, meter never set (backdated assign) -> owes 16..28 Jun
    db.execute(
        "INSERT INTO ev_assignments (person_id,ev_id,handover_date) VALUES (?, 'EVBD', '2026-06-15')",  # noqa: E501
        (pid,),
    )
    db.commit()
    info = compute_backrent(db, pid, "2026-06-28")
    assert info["days"] == 13  # 16..28 Jun inclusive
    assert info["amount"] == 234000  # 1260/wk * 13/7 = 2340.00 -> paise
    res = apply_backrent(db, pid, "2026-06-28", "op@x.com")
    db.commit()
    assert res["added"] == 234000
    total_missed, _rec, outstanding = get_arrears(db, pid)
    assert outstanding == 234000
    # meter advanced -> a later cycle bills only its own 7 days
    from datetime import date

    from payout.domain.rent import resolve_rent

    r = resolve_rent(db, pid, date(2026, 6, 29), date(2026, 7, 5))
    assert r.days == 7
