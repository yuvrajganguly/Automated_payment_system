"""An EV assignment cannot exist without a handover date.

Reported 2026-09 from a live payout as two separate complaints that turned out
to be one bug:

  * Somnath Sardar was charged rent twice in one cycle after his EV was taken
    off him and another handed over.
  * Sahil was charged 1,295 for a cycle he spent on a 1,260 EV — the 1,295 one
    reached him only after that cycle had closed.

Both were ``ev_assignments.handover_date`` being NULL. The column was nullable
and the schema described NULL as "rent the full cycle (legacy riders)", which
held while the only NULL rows came from the go-live import. Once the EV screens
and the payout importer could write NULL too, an assignment with no date had
nothing to compare a cycle against: rent billed it for every cycle, in full, at
its own EV's rate, forever.

The column is NOT NULL now, so most of this file cannot test the bug directly —
it tests that the shape is unreachable, that the migration removed the rows
that had it, and that the arithmetic is right when the dates are real.
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


def test_the_column_refuses_a_missing_handover_date(db):
    """The shape that caused the double charge cannot be written any more."""
    p = make_person(db, "No date")
    make_ev(db, "EV-Z", provider="Blive", model="Standard")
    with pytest.raises(Exception, match="(?i)not null|null value"):
        db.execute(
            "INSERT INTO ev_assignments (person_id, ev_id, handover_date) VALUES (?, ?, NULL)",
            (p, "EV-Z"),
        )
    db.rollback()


def test_the_migration_backfills_the_rows_that_already_had_none(monkeypatch):
    """Existing NULLs become the day the row was written — the honest floor,
    since we cannot have handed a vehicle over before recording that we had.

    Run against a connection built with the **pre-0029** shape, because the
    live schema will not hold a NULL any more: the only place that row can
    still exist is a database that has not had this migration yet, which is
    exactly what is being simulated.
    """
    import sqlite3

    from payout.db import migrations
    from payout.db.migrations import _0029_handover_date_required

    # The probe connection is SQLite whichever backend the suite is running
    # against, so the Postgres-only ALTER is out of scope here. What is under
    # test is the backfill, and it is identical on both.
    monkeypatch.setattr(migrations, "DB_URL", None)

    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE ev_assignments ("
        "  assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  person_id INTEGER, ev_id TEXT,"
        "  handover_date TEXT, created_at TEXT);"
        "CREATE TABLE company_cycles (company TEXT, cycle_start TEXT);"
    )
    conn.execute("INSERT INTO company_cycles VALUES ('Shadowfax', '2026-05-04')")
    conn.executemany(
        "INSERT INTO ev_assignments (person_id, ev_id, handover_date, created_at) VALUES (?,?,?,?)",
        [
            (1, "EV-DATED", "2026-08-01", "2026-08-01 09:00:00"),  # already fine
            (2, "EV-NULL", None, "2026-07-04 09:00:00"),  # backfilled from created_at
            (3, "EV-ANCIENT", None, None),  # nothing to go on
        ],
    )

    _0029_handover_date_required(conn)

    got = {
        r["ev_id"]: r["handover_date"]
        for r in conn.execute("SELECT ev_id, handover_date FROM ev_assignments")
    }
    assert got["EV-DATED"] == "2026-08-01", "a good date must not be rewritten"
    assert got["EV-NULL"] == "2026-07-04"
    # No created_at either: the earliest cycle the office ever ran. Too early
    # can only under-charge; too late takes money for days nobody can evidence.
    assert got["EV-ANCIENT"] == "2026-05-04"

    # Idempotent — a second run changes nothing.
    _0029_handover_date_required(conn)
    assert {
        r["ev_id"]: r["handover_date"]
        for r in conn.execute("SELECT ev_id, handover_date FROM ev_assignments")
    } == got
    conn.close()


def test_a_clean_swap_bills_each_ev_for_its_own_days(db, rates):
    """Somnath, with the dates the app now always records. The engine was
    always right here — handover day and return day are both free, so a swap
    costs a day rather than doubling."""
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
    assert r.rent == 108000  # 6 × ₹180, not 14 days across two EVs
    assert [(leg.ev_id, leg.days) for leg in r.legs] == [("EV-A", 3), ("EV-B", 3)]


def test_an_ev_that_arrived_after_the_cycle_does_not_set_the_cycles_rate(db, rates):
    """Sahil. The ₹1,295 EV reached him after the cycle ended; the week he
    worked was on the ₹1,260 one, and that is what the cycle charges."""
    p = make_person(db, "Sahil")
    make_ev(db, "EV-OLD", provider="Blive", model="Standard")  # ₹1,260
    make_ev(db, "EV-NEW", provider="Raft", model="Regular")  # ₹1,295
    assign(db, p, "EV-OLD", handover="2026-08-01", returned="2026-09-02")
    assign(db, p, "EV-NEW", handover="2026-09-02")
    db.commit()

    r = _rent(db, p)
    assert [leg.ev_id for leg in r.legs] == ["EV-OLD"]
    assert r.rent == 126000, "charged at the rate of an EV he did not have that week"


def test_a_handover_inside_the_cycle_bills_from_the_day_after(db, rates):
    """The floor is a floor, not an amnesty: once the vehicle is out, rent
    runs. Only the days before it was handed over are out of reach."""
    p = make_person(db, "Mid-cycle")
    make_ev(db, "EV-C", provider="Blive", model="Standard")
    assign(db, p, "EV-C", handover="2026-08-26")
    db.commit()

    r = _rent(db, p)
    assert r.days == 4  # handover day free → 27–30
    assert r.rent == 72000


def test_handing_over_an_ev_never_writes_a_null_handover_date(db):
    """The route that made most of the bad rows now dates them itself, so the
    app can keep sending nothing and still be correct."""
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
