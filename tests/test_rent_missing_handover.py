"""An assignment with no handover date must not bill cycles it was not in.

Reported 2026-09 from a live payout, as two separate complaints that turned
out to be one bug:

  * Somnath Sardar was charged rent twice in one cycle after his EV was taken
    off him and another handed over.
  * Sahil was charged 1,295 for a cycle he spent on a 1,260 EV — the 1,295 one
    reached him only after that cycle had closed.

Both are ``ev_assignments.handover_date`` being NULL. The column is nullable
and the schema described NULL as "rent the full cycle (legacy riders)", which
was true when the only NULL rows came from the go-live import. Once the EV
screens and the payout importer could write NULL too, an assignment with no
date had nothing to compare a cycle against: ``resolve_rent`` billed it for
every cycle, in full, at its own EV's rate, forever.
"""

from __future__ import annotations

from datetime import date

import pytest

from tests.conftest import assign, make_ev, make_person

CYCLE_START, CYCLE_END = date(2026, 8, 24), date(2026, 8, 30)  # a 7-day cycle


@pytest.fixture
def rates(db):
    """Two EV models a week apart in price: ₹1,260 and ₹1,295."""
    db.execute(
        "UPDATE ev_models SET weekly_rate=126000 WHERE provider='Blive' AND model_name='Standard'"
    )
    db.execute(
        "UPDATE ev_models SET weekly_rate=129500 WHERE provider='Raft' AND model_name='Regular'"
    )
    db.commit()


def _rent(db, person_id):
    from payout.domain.rent import resolve_rent

    return resolve_rent(db, person_id, CYCLE_START, CYCLE_END)


def test_a_clean_swap_bills_each_ev_for_its_own_days(db, rates):
    """The control. With both dates recorded the engine was always right —
    handover day and return day are free, so a swap costs a day, not double."""
    p = make_person(db, "Somnath Sardar")
    make_ev(db, "EV-A", provider="Blive", model="Standard")
    make_ev(db, "EV-B", provider="Blive", model="Standard")
    assign(
        db, p, "EV-A", handover="2026-08-01", returned="2026-08-27", charged_through="2026-08-23"
    )
    assign(db, p, "EV-B", handover="2026-08-27")
    db.commit()

    r = _rent(db, p)
    assert r.days == 6  # 24–26 on EV-A, 28–30 on EV-B; the 27th is free
    assert r.rent == 108000  # 6 × ₹180
    assert [(leg.ev_id, leg.days) for leg in r.legs] == [("EV-A", 3), ("EV-B", 3)]


def test_the_reassigned_ev_without_a_handover_date_does_not_bill_the_cycle_twice(db, rates):
    """Somnath. The replacement EV's row was written on 3 September with no
    handover date; before the fix it billed the whole August cycle as well."""
    p = make_person(db, "Somnath Sardar")
    make_ev(db, "EV-A", provider="Blive", model="Standard")
    make_ev(db, "EV-B", provider="Blive", model="Standard")
    assign(
        db, p, "EV-A", handover="2026-08-01", returned="2026-09-03", charged_through="2026-08-23"
    )
    aid = assign(db, p, "EV-B", handover=None)
    db.execute(
        "UPDATE ev_assignments SET created_at='2026-09-03 10:00:00' WHERE assignment_id=?", (aid,)
    )
    db.commit()

    r = _rent(db, p)
    # Only the EV he actually had that week. EV-B was created after the cycle
    # closed, so it contributes nothing to it.
    assert [leg.ev_id for leg in r.legs] == ["EV-A"]
    assert r.days == 7
    assert r.rent == 126000  # ₹1,260 once, not ₹2,555


def test_an_ev_that_arrived_after_the_cycle_does_not_set_the_cycles_rate(db, rates):
    """Sahil. The ₹1,295 EV reached him after the cycle ended; the week he
    worked was on the ₹1,260 one, and that is what the cycle must charge."""
    p = make_person(db, "Sahil")
    make_ev(db, "EV-OLD", provider="Blive", model="Standard")  # ₹1,260
    make_ev(db, "EV-NEW", provider="Raft", model="Regular")  # ₹1,295
    assign(db, p, "EV-OLD", handover="2026-08-01", returned="2026-09-02")
    aid = assign(db, p, "EV-NEW", handover=None)
    db.execute(
        "UPDATE ev_assignments SET created_at='2026-09-02 09:30:00' WHERE assignment_id=?", (aid,)
    )
    db.commit()

    r = _rent(db, p)
    assert [leg.ev_id for leg in r.legs] == ["EV-OLD"]
    assert r.rent == 126000, "charged at the rate of an EV he did not have that week"


def test_a_dateless_assignment_still_bills_from_the_day_it_was_created(db, rates):
    """The fallback is a floor, not an amnesty: once the row exists, the rent
    runs. Only the days before it existed are out of reach."""
    p = make_person(db, "Late paperwork")
    make_ev(db, "EV-C", provider="Blive", model="Standard")
    aid = assign(db, p, "EV-C", handover=None)
    db.execute(
        "UPDATE ev_assignments SET created_at='2026-08-26 12:00:00' WHERE assignment_id=?", (aid,)
    )
    db.commit()

    r = _rent(db, p)
    assert r.days == 4  # created on the 26th, handover day free → 27–30
    assert r.legs[0].assumed_handover is True


def test_an_assignment_with_no_dates_at_all_takes_no_money(db, rates):
    """Both columns empty: the row cannot say when it began, so it does not
    charge. Under-charging is recoverable; taking money we cannot justify is
    the thing that reached a rider's payslip."""
    p = make_person(db, "No dates")
    make_ev(db, "EV-D", provider="Blive", model="Standard")
    aid = assign(db, p, "EV-D", handover=None)
    db.execute("UPDATE ev_assignments SET created_at=NULL WHERE assignment_id=?", (aid,))
    db.commit()

    r = _rent(db, p)
    assert r.rent == 0 and r.days == 0


def test_handing_over_an_ev_never_writes_a_null_handover_date(db):
    """The route that made most of these rows now dates them itself."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("boss@t.test", hash_password("Creator-pass-1"), "creator"),
    )
    p = make_person(db, "Arjun Das")
    make_ev(db, "EV-E", provider="Blive", model="Standard")
    db.commit()
    ratelimit.reset()

    with TestClient(app) as client:
        tok = client.post(
            "/api/auth/login", data={"username": "boss@t.test", "password": "Creator-pass-1"}
        ).json()["access_token"]
        r = client.post(
            "/api/evs/assign",
            json={"ev_id": "EV-E", "person_id": p},  # no handover_date sent
            headers={"Authorization": "Bearer " + tok},
        )
        assert r.status_code in (200, 201), r.text

    row = db.execute("SELECT handover_date FROM ev_assignments WHERE ev_id='EV-E'").fetchone()
    assert row["handover_date"] == date.today().isoformat()
