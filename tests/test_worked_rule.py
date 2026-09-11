"""Is this rider working? (domain/worked.py, rewritten 2026-09-11)

The rule: of the rider ids a person holds that are still switched on, at a
company that sends us a paysheet, that existed when that company's last cycle
began — did any appear in that cycle's payout? If none did, they are not
working. If we expected them nowhere, we say nothing.

What it replaced was "paid for a cycle ending in the last 12 days", whose own
docstring admitted the flaw these tests are mostly about: absence of a payout
run is not absence of work.
"""

from __future__ import annotations

import pytest

from tests.conftest import make_person, make_rider


@pytest.fixture
def client(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("adm@t.test", hash_password("Admin-pass-1"), "admin"),
    )
    # Kaptan and Jiffy send paysheets; Shadowfax is per_order and never does.
    db.execute(
        "UPDATE companies SET payment_model='payout_file' WHERE company_name IN ('Kaptan', 'Jiffy')"
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        assert (
            c.post(
                "/api/auth/login", data={"username": "adm@t.test", "password": "Admin-pass-1"}
            ).status_code
            == 200
        )
        yield c


def _cycle(db, company, start, end, bucket="2026-W37"):
    db.execute(
        "INSERT INTO company_cycles (company, cycle_start, cycle_end, week_bucket) "
        "VALUES (?,?,?,?)",
        (company, start, end, bucket),
    )


def _paid(db, person_id, rider_id, company, start, end):
    db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, event_type, amount, "
        "  balance_after, cycle_start, cycle_end) VALUES (?,?,?,'PAYOUT',100000,100000,?,?)",
        (person_id, rider_id, company, start, end),
    )


def _rider(db, pid, rider_id, company, created="2026-01-01 09:00:00", active=1):
    make_rider(db, pid, rider_id, company, "Rider")
    db.execute(
        "UPDATE rider_master SET created_at=?, is_active=? WHERE rider_id=? AND company=?",
        (created, active, rider_id, company),
    )


def _working(client, rider_id):
    rows = client.get("/api/riders").json()
    row = next(r for r in rows if r["rider_id"] == rider_id)
    return row["working"]


# ── the plain cases ──────────────────────────────────────────────────────────


def test_in_the_last_payout_is_working(db, client):
    pid = make_person(db, "Present")
    _rider(db, pid, "K-1", "Kaptan")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    _paid(db, pid, "K-1", "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is True


def test_missing_from_the_last_payout_is_not_working(db, client):
    pid = make_person(db, "Absent")
    _rider(db, pid, "K-1", "Kaptan")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is False


def test_an_older_payout_does_not_count(db, client):
    """Only the LAST cycle is evidence. Present two cycles ago and absent from
    the most recent one is exactly the rider the office wants flagged."""
    pid = make_person(db, "Lapsed")
    _rider(db, pid, "K-1", "Kaptan")
    _cycle(db, "Kaptan", "2026-08-25", "2026-08-31", "2026-W35")
    _paid(db, pid, "K-1", "Kaptan", "2026-08-25", "2026-08-31")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is False


# ── the exemptions ───────────────────────────────────────────────────────────


def test_a_switched_off_id_is_not_expected(db, client):
    """The recruiter marked them gone from this company, so their absence from
    the payout is the expected outcome, not evidence of idleness."""
    pid = make_person(db, "Marked Inactive")
    _rider(db, pid, "K-1", "Kaptan", active=0)
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is True, "switched off means unexpected, not idle"


def test_too_new_to_have_been_in_it(db, client):
    pid = make_person(db, "Brand New")
    _rider(db, pid, "K-1", "Kaptan", created="2026-09-09 10:00:00")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is True


def test_created_on_the_cycle_start_day_is_still_judged(db, client):
    """They could have ridden that day, so the exemption does not apply."""
    pid = make_person(db, "Same Day")
    _rider(db, pid, "K-1", "Kaptan", created="2026-09-01 08:00:00")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is False


def test_the_exemption_expires_by_itself(db, client):
    """Same rider, same row — a newer cycle makes them expectant with no
    change to the rider and no arbitrary number of days anywhere."""
    pid = make_person(db, "Was New")
    _rider(db, pid, "K-1", "Kaptan", created="2026-09-09 10:00:00")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is True
    _cycle(db, "Kaptan", "2026-09-15", "2026-09-21", "2026-W38")
    db.commit()
    assert _working(client, "K-1") is False


def test_a_company_that_never_reports_cannot_accuse(db, client):
    """Shadowfax is per_order — we read order counts off a dashboard and never
    see a payout file, so its silence says nothing about the rider."""
    pid = make_person(db, "Per Order")
    _rider(db, pid, "SF-1", "Shadowfax")
    _cycle(db, "Shadowfax", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "SF-1") is True


def test_a_company_that_has_never_run_a_cycle(db, client):
    pid = make_person(db, "No Cycles Yet")
    _rider(db, pid, "K-1", "Kaptan")
    db.commit()
    assert _working(client, "K-1") is True, "nothing to be absent from"


# ── more than one id ─────────────────────────────────────────────────────────


def test_present_at_one_company_is_enough(db, client):
    """The question is about a person, not a row. Working Kaptan and idle at
    Jiffy is working."""
    pid = make_person(db, "Two Ids")
    _rider(db, pid, "K-1", "Kaptan")
    _rider(db, pid, "J-1", "Jiffy")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    _cycle(db, "Jiffy", "2026-09-01", "2026-09-07")
    _paid(db, pid, "K-1", "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is True
    assert _working(client, "J-1") is True, "the flag is the person's, not the id's"


def test_absent_at_every_expectant_company(db, client):
    pid = make_person(db, "Gone Everywhere")
    _rider(db, pid, "K-1", "Kaptan")
    _rider(db, pid, "J-1", "Jiffy")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    _cycle(db, "Jiffy", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is False


def test_one_id_switched_off_the_other_paid(db, client):
    """The case this rule was written for: a rider with several ids whose
    recruiter switched off the one they left."""
    pid = make_person(db, "Left Jiffy")
    _rider(db, pid, "K-1", "Kaptan")
    _rider(db, pid, "J-1", "Jiffy", active=0)
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    _cycle(db, "Jiffy", "2026-09-01", "2026-09-07")
    _paid(db, pid, "K-1", "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is True


def test_every_id_switched_off_is_not_an_accusation(db, client):
    """All ids off means nobody expected them anywhere. That is a roster
    question (on_roster), not a working one — and the two are reported
    separately precisely so this case does not lie."""
    pid = make_person(db, "All Off")
    _rider(db, pid, "K-1", "Kaptan", active=0)
    _rider(db, pid, "J-1", "Jiffy", active=0)
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is True


def test_the_other_ids_absence_still_counts(db, client):
    """Two live ids, one company ran and did not pay them, the other never
    ran. The one that ran is evidence; the silent one is not. Absent from the
    only company that could report → not working."""
    pid = make_person(db, "Half Silent")
    _rider(db, pid, "K-1", "Kaptan")
    _rider(db, pid, "SF-1", "Shadowfax")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is False


# ── the guarantee that outlives the data ─────────────────────────────────────


def test_deleting_a_company_does_not_flip_a_rider_to_idle(db, client):
    """The ledger outlives the companies row. An INNER JOIN here would
    silently flip every rider a deleted company ever paid from working to
    idle, and the number would just quietly become wrong."""
    pid = make_person(db, "Orphaned")
    _rider(db, pid, "K-1", "Kaptan")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    _paid(db, pid, "K-1", "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is True
    db.execute("DELETE FROM companies WHERE company_name='Kaptan'")
    db.commit()
    assert _working(client, "K-1") is True


def test_an_unrelated_payout_does_not_make_anyone_working(db, client):
    """The rule correlates on person_id AND company. An unqualified column
    would bind to the subquery's own row and turn this into "has anyone,
    anywhere, been paid"."""
    absent = make_person(db, "Absent")
    _rider(db, absent, "K-1", "Kaptan")
    other = make_person(db, "Paid")
    _rider(db, other, "K-2", "Kaptan")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    _paid(db, other, "K-2", "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-2") is True
    assert _working(client, "K-1") is False


def test_a_payout_at_the_wrong_company_is_not_evidence(db, client):
    """Paid by Jiffy, absent from Kaptan's last run. Jiffy's payment is
    evidence for the Jiffy id, and Kaptan's silence for the Kaptan one — but
    the person only needs one, so they are working. What must NOT happen is
    Kaptan's id being credited with Jiffy's payout row."""
    pid = make_person(db, "Cross")
    _rider(db, pid, "K-1", "Kaptan")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    _paid(db, pid, "J-9", "Jiffy", "2026-09-01", "2026-09-07")
    db.commit()
    # The only live id is at Kaptan, which ran and did not pay them.
    assert _working(client, "K-1") is False


# ── a company the office has switched off ────────────────────────────────────


def test_a_switched_off_company_stops_accusing(db, client):
    """Kaptan ran a cycle, did not pay this rider, and has since been switched
    off. Without this the rider reads idle for ever: a dead company's last
    cycle stays "the last cycle" permanently, so the absence never expires and
    the number ends up measuring our own decision to stop running Kaptan."""
    pid = make_person(db, "Company Closed")
    _rider(db, pid, "K-1", "Kaptan")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "K-1") is False
    db.execute("UPDATE companies SET is_active=0 WHERE company_name='Kaptan'")
    db.commit()
    assert _working(client, "K-1") is True, "nobody expects work from a company we stopped"


def test_switching_a_company_off_does_not_hide_work_elsewhere(db, client):
    """The exemption is per id, not per person. Kaptan off, Jiffy live and
    silent about them → still judged by Jiffy."""
    pid = make_person(db, "Two Companies")
    _rider(db, pid, "K-1", "Kaptan")
    _rider(db, pid, "J-1", "Jiffy")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    _cycle(db, "Jiffy", "2026-09-01", "2026-09-07")
    _paid(db, pid, "K-1", "Kaptan", "2026-09-01", "2026-09-07")
    db.commit()
    assert _working(client, "J-1") is True, "Kaptan paid them, so the person is working"
    db.execute("UPDATE companies SET is_active=0 WHERE company_name='Kaptan'")
    db.commit()
    # Kaptan's payout is no longer evidence for anything; Jiffy ran and did not
    # pay them, and Jiffy is the only company still expecting them.
    assert _working(client, "J-1") is False


def test_switching_a_company_back_on_restores_the_test(db, client):
    pid = make_person(db, "Reopened")
    _rider(db, pid, "K-1", "Kaptan")
    _cycle(db, "Kaptan", "2026-09-01", "2026-09-07")
    db.execute("UPDATE companies SET is_active=0 WHERE company_name='Kaptan'")
    db.commit()
    assert _working(client, "K-1") is True
    db.execute("UPDATE companies SET is_active=1 WHERE company_name='Kaptan'")
    db.commit()
    assert _working(client, "K-1") is False
