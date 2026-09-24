"""What the rider pays and what we pay the provider are two numbers.

`ev_models.weekly_rate` was doing both jobs: the rider's rent AND
`ev_daily_ledger.provider_cost`, which every per-EV P&L subtracts. Raft's W38
bill (14-20 September 2026) shows 1,225 a week for CBICEVD units we rent at
1,295, and 1,050 for the older trackers we rent at 1,250 — so the ledger had
been recording a cost higher than the invoice for every vehicle, every week.
"""

from __future__ import annotations

from datetime import date, timedelta

from tests.conftest import assign, make_ev, make_person


def _rates(db, provider="Raft", model="Blue"):
    return db.execute(
        "SELECT weekly_rate, provider_rate FROM ev_models WHERE provider=? AND model_name=?",
        (provider, model),
    ).fetchone()


def test_raft_arrives_with_the_rates_off_the_bill(db):
    blue, regular = _rates(db), _rates(db, model="Regular")
    assert (int(blue["weekly_rate"]), int(blue["provider_rate"])) == (129500, 122500)
    assert (int(regular["weekly_rate"]), int(regular["provider_rate"])) == (125000, 105000)


def test_a_model_with_no_provider_rate_behaves_exactly_as_before(db):
    """NULL means "the same". Nothing moves on its own."""
    blive = _rates(db, provider="Blive", model="Standard")
    assert blive["provider_rate"] is None


def test_the_ledger_records_the_invoice_not_the_rider_rate(db):
    """The whole point: provider_cost is what Raft will bill, daily_cost is
    what the rider owes, and they are no longer the same number."""
    from payout.domain.ev_daily import materialize_cycle_for_person
    from payout.domain.rent import resolve_rent

    start = date(2026, 9, 14)
    end = date(2026, 9, 20)
    pid = make_person(db, "Jit Dey", balance=0, arrears=0)
    make_ev(db, "CBICEVD0292", provider="Raft", model="Blue", status="in_use")
    assign(
        db,
        pid,
        "CBICEVD0292",
        handover="2026-09-01",
        charged_through=(start - timedelta(days=1)).isoformat(),
    )
    db.commit()

    info = resolve_rent(db, pid, start, end)
    materialize_cycle_for_person(
        db,
        person_id=pid,
        cycle_start=start,
        cycle_end=end,
        legs=info.legs,
        billing_event_id=None,
        billing_status="billed",
    )
    db.commit()

    rows = db.execute(
        "SELECT SUM(daily_cost) AS rider, SUM(provider_cost) AS provider "
        "FROM ev_daily_ledger WHERE ev_id='CBICEVD0292' AND state='billable'"
    ).fetchone()
    # A full week at 1,295 to the rider; 1,225 owed to Raft. The margin is the
    # 70 that used to be invisible because both sides read one column.
    assert int(rows["rider"]) == 129500
    assert int(rows["provider"]) == round(122500 / 7) * 7


def test_the_rider_is_still_charged_the_rider_rate(db):
    """Splitting the cost out must not quietly change anybody's rent."""
    from payout.domain.rent import resolve_rent

    start, end = date(2026, 9, 14), date(2026, 9, 20)
    pid = make_person(db, "Unchanged", balance=0, arrears=0)
    make_ev(db, "CBICEVD0293", provider="Raft", model="Blue", status="in_use")
    assign(
        db,
        pid,
        "CBICEVD0293",
        handover="2026-09-01",
        charged_through=(start - timedelta(days=1)).isoformat(),
    )
    db.commit()
    assert int(resolve_rent(db, pid, start, end).rent) == 129500


def test_a_model_without_the_split_still_bills_one_number(db):
    from payout.domain.ev_daily import materialize_cycle_for_person
    from payout.domain.rent import resolve_rent

    start, end = date(2026, 9, 14), date(2026, 9, 20)
    pid = make_person(db, "Blive Rider", balance=0, arrears=0)
    make_ev(db, "KOL0001", provider="Blive", model="Standard", status="in_use")
    assign(
        db,
        pid,
        "KOL0001",
        handover="2026-09-01",
        charged_through=(start - timedelta(days=1)).isoformat(),
    )
    db.commit()
    info = resolve_rent(db, pid, start, end)
    materialize_cycle_for_person(
        db,
        person_id=pid,
        cycle_start=start,
        cycle_end=end,
        legs=info.legs,
        billing_event_id=None,
        billing_status="billed",
    )
    db.commit()
    rows = db.execute(
        "SELECT SUM(daily_cost) AS rider, SUM(provider_cost) AS provider "
        "FROM ev_daily_ledger WHERE ev_id='KOL0001' AND state='billable'"
    ).fetchone()
    assert int(rows["rider"]) == 126000
    assert int(rows["provider"]) == round(126000 / 7) * 7
