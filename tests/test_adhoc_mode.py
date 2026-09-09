"""Ad-hoc payouts: money that is not a cycle.

Companies hitting a surge hire riders from outside for a day or three and pay
them separately. The office receives a file for money already agreed and has to
put it through the books — no window, no rent, nothing to reconcile against a
week.

Every assertion here is a thing that would cost real money if the gate were
missing, so each test says which one.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from openpyxl import Workbook

from payout.domain.engine import CycleAlreadyCommitted, process_cycle
from tests.conftest import assign, make_ev, make_person, make_rider

DAY = date(2026, 8, 27)
WEEK = (date(2026, 8, 24), date(2026, 8, 30))


def _file(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["rider_id", "rider_name", "hub", "total_del", "net_pay"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _events(db, person_id=None):
    sql = "SELECT event_type, amount, person_id FROM transactions"
    return [dict(r) for r in db.execute(sql)]


@pytest.fixture
def ev_rider(db):
    """A regular rider on one of our EVs, mid-cycle, meter already running."""
    p = make_person(db, "Regular Rider", balance=0)
    make_rider(db, p, "31111", "Kaptan", "Regular Rider")
    make_ev(db, "EV-R", provider="Blive", model="Standard")
    assign(db, p, "EV-R", handover="2026-08-01", charged_through="2026-08-23")
    db.commit()
    return p


def test_an_adhoc_run_charges_no_rent(db, ev_rider):
    """A rider picking up surge days must not be billed a second week for the
    EV their normal cycle is already billing."""
    r = process_cycle(
        "Kaptan",
        DAY,
        DAY,
        _file([["31111", "Regular Rider", "H", 9, 800]]),
        commit=True,
        ad_hoc=True,
    )
    assert r.committed, r.errors
    kinds = {e["event_type"] for e in _events(db)}
    assert "RENT" not in kinds
    assert r.pay_rows[0].released == 80000  # paise; the engine works in paise


def test_an_adhoc_run_does_not_move_the_rent_meter(db, ev_rider):
    """The gate that would be most expensive to get wrong: advancing the meter
    here means the normal cycle finds the days already billed and gifts a week
    of rent to whoever appeared in the surge file."""
    before = db.execute(
        "SELECT rent_charged_through FROM ev_assignments WHERE ev_id='EV-R'"
    ).fetchone()[0]
    process_cycle(
        "Kaptan",
        DAY,
        DAY,
        _file([["31111", "Regular Rider", "H", 9, 800]]),
        commit=True,
        ad_hoc=True,
    )
    after = db.execute(
        "SELECT rent_charged_through FROM ev_assignments WHERE ev_id='EV-R'"
    ).fetchone()[0]
    assert after == before == "2026-08-23"


def test_an_adhoc_run_does_not_mark_the_rest_of_the_roster_absent(db, ev_rider):
    """The dangerous one. A surge file lists a handful of people; everybody
    else is missing because they were not part of that arrangement. A normal
    cycle would read that as absence and charge the whole roster arrears."""
    other = make_person(db, "Not In The Surge File", balance=0)
    make_rider(db, other, "22222", "Kaptan", "Not In The Surge File")
    make_ev(db, "EV-O", provider="Blive", model="Standard")
    assign(db, other, "EV-O", handover="2026-08-01", charged_through="2026-08-23")
    db.commit()

    r = process_cycle(
        "Kaptan",
        DAY,
        DAY,
        _file([["31111", "Regular Rider", "H", 9, 800]]),
        commit=True,
        ad_hoc=True,
    )
    assert r.committed, r.errors
    assert not [e for e in _events(db) if e["event_type"] == "RENT_MISSED"]
    assert (
        db.execute(
            "SELECT COALESCE(outstanding, 0) FROM ev_arrears WHERE person_id=?", (other,)
        ).fetchone()
        is None
        or db.execute(
            "SELECT COALESCE(outstanding, 0) FROM ev_arrears WHERE person_id=?", (other,)
        ).fetchone()[0]
        == 0
    )


def test_an_adhoc_run_leaves_the_week_unpaid(db, ev_rider):
    """No company_cycles row, so the normal cycle still runs — and when it
    does, it bills the rent the ad-hoc run correctly left alone."""
    process_cycle(
        "Kaptan",
        DAY,
        DAY,
        _file([["31111", "Regular Rider", "H", 9, 800]]),
        commit=True,
        ad_hoc=True,
    )
    assert db.execute("SELECT COUNT(*) FROM company_cycles").fetchone()[0] == 0

    normal = process_cycle(
        "Kaptan", *WEEK, _file([["31111", "Regular Rider", "H", 40, 3000]]), commit=True
    )
    assert normal.committed, normal.errors
    assert db.execute("SELECT COUNT(*) FROM company_cycles").fetchone()[0] == 1
    rent = [e for e in _events(db) if e["event_type"] == "RENT"]
    assert rent, "the normal cycle must still bill the rent"


def test_it_still_recovers_what_they_owe(db):
    """Not a free pass. If the person turns out to be one of ours carrying old
    dues, this settles like any other payment."""
    p = make_person(db, "Owes Us", balance=-50000)  # ₹500 in the red
    make_rider(db, p, "31111", "Kaptan", "Owes Us")
    db.commit()

    r = process_cycle(
        "Kaptan", DAY, DAY, _file([["31111", "Owes Us", "H", 9, 800]]), commit=True, ad_hoc=True
    )
    assert r.committed, r.errors
    assert r.pay_rows[0].released == 30000  # ₹800 paid, ₹500 of dues cleared
    assert (
        db.execute("SELECT current_balance FROM balances WHERE person_id=?", (p,)).fetchone()[0]
        == 0
    )


def test_the_same_surge_file_cannot_be_paid_twice(db, ev_rider):
    """There is no cycle window to guard this, so the file's own content is
    the identity: same company, same riders, same amounts is a repeat."""
    data = _file([["31111", "Regular Rider", "H", 9, 800]])
    assert process_cycle("Kaptan", DAY, DAY, data, commit=True, ad_hoc=True).committed
    with pytest.raises(CycleAlreadyCommitted, match="already been processed"):
        process_cycle("Kaptan", DAY, DAY, data, commit=True, ad_hoc=True)

    # A different surge, same day, goes through — it is different money.
    other = _file([["31111", "Regular Rider", "H", 4, 450]])
    assert process_cycle("Kaptan", DAY, DAY, other, commit=True, ad_hoc=True).committed
    assert db.execute("SELECT COUNT(*) FROM adhoc_runs").fetchone()[0] == 2


def test_force_lets_an_operator_redo_one_deliberately(db, ev_rider):
    data = _file([["31111", "Regular Rider", "H", 9, 800]])
    process_cycle("Kaptan", DAY, DAY, data, commit=True, ad_hoc=True)
    r = process_cycle("Kaptan", DAY, DAY, data, commit=True, ad_hoc=True, force=True)
    assert r.committed
    assert db.execute("SELECT COUNT(*) FROM adhoc_runs").fetchone()[0] == 1


def test_a_dry_run_writes_nothing_and_names_no_run(db, ev_rider):
    data = _file([["31111", "Regular Rider", "H", 9, 800]])
    r = process_cycle("Kaptan", DAY, DAY, data, commit=False, ad_hoc=True)
    assert not r.committed
    assert db.execute("SELECT COUNT(*) FROM adhoc_runs").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    assert r.pay_rows[0].released == 80000  # the preview still shows the money
