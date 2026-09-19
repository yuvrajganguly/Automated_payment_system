"""The "this cannot be true" page (2026-09-19).

Each check below is a real September 2026 incident reduced to its smallest
shape. The negative cases are the load-bearing ones: a page that cries wolf
gets closed, and then the one true finding on it goes unread too.
"""

from __future__ import annotations

import pytest

from payout.domain.anomalies import run_checks
from tests.conftest import assign, make_ev, make_person, make_rider


def _kinds(findings) -> set[str]:
    return {f["check"] for f in findings}


def _of(findings, check) -> list[dict]:
    return [f for f in findings if f["check"] == check]


def test_a_clean_database_reports_nothing(db):
    pid = make_person(db, "Nobody Special")
    make_rider(db, pid, "R-1", "Jiffy", "Nobody Special")
    make_ev(db, "CBICEVD0250", provider="Raft", model="Blue", status="in_use")
    assign(db, pid, "CBICEVD0250", handover="2026-09-01")
    db.commit()
    assert run_checks(db) == []


# ── identity ─────────────────────────────────────────────────────────────────
def test_it_finds_the_two_phantom_ev_ids(db):
    make_ev(db, "CBICEVD0250", provider="Raft", model="Blue", status="spare")
    make_ev(db, "CBJCEVD0250", provider="Raft", model="Blue", status="spare")
    db.commit()
    hit = _of(run_checks(db), "confusable_ev_ids")
    assert len(hit) == 1
    assert set(hit[0]["ev_ids"]) == {"CBICEVD0250", "CBJCEVD0250"}
    assert hit[0]["fix"]


def test_it_names_who_is_holding_the_phantom(db):
    """Without the holder the finding is a puzzle; with it, it is an errand."""
    pid = make_person(db, "Shibam Pramanick")
    make_ev(db, "CBICEVD0286", provider="Raft", model="Blue", status="spare")
    make_ev(db, "CBICEVDO286", provider="Raft", model="Blue", status="in_use")
    assign(db, pid, "CBICEVDO286", handover="2026-09-12")
    db.commit()
    assert "Shibam Pramanick" in _of(run_checks(db), "confusable_ev_ids")[0]["detail"]


def test_it_finds_the_rider_id_typo(db):
    a, b = make_person(db, "Suman Mondal"), make_person(db, "Suman Two")
    make_rider(db, a, "67163_MNOW000471", "Myntra", "Suman Mondal")
    make_rider(db, b, "67163_MN0W000471", "Myntra", "Suman Two")
    db.commit()
    assert len(_of(run_checks(db), "confusable_rider_ids")) == 1


def test_the_same_rider_id_at_two_companies_is_not_a_typo(db):
    """Nykaa pays Blitz riders under their Blitz IDs. Flagging that would make
    the page useless on day one."""
    a, b = make_person(db, "A"), make_person(db, "B")
    make_rider(db, a, "R-77", "Blitz", "A")
    make_rider(db, b, "R-77", "Nykaa", "B")
    db.commit()
    assert "confusable_rider_ids" not in _kinds(run_checks(db))


def test_it_finds_the_same_man_recorded_twice(db):
    a, b = make_person(db, "SUSANTA GHOSH"), make_person(db, "Sushanta ghosh")
    make_rider(db, a, "R-1", "Jiffy", "SUSANTA GHOSH")
    make_rider(db, b, "R-2", "Myntra", "Sushanta ghosh")
    db.execute("UPDATE rider_master SET mob_no='7432856791'")
    db.commit()
    hit = _of(run_checks(db), "duplicate_people")
    assert len(hit) == 1
    assert "phone=7432856791" in hit[0]["detail"]
    assert set(hit[0]["person_ids"]) == {a, b}


def test_two_men_with_one_name_and_no_shared_anything_are_left_alone(db):
    """There are around thirty of these. Listing them here would bury the
    findings that are certain."""
    a, b = make_person(db, "Rahul Das"), make_person(db, "Rahul Das")
    make_rider(db, a, "R-1", "Jiffy", "Rahul Das")
    make_rider(db, b, "R-2", "Jiffy", "Rahul Das")
    db.execute("UPDATE rider_master SET mob_no='9000000001' WHERE rider_id='R-1'")
    db.execute("UPDATE rider_master SET mob_no='9000000002' WHERE rider_id='R-2'")
    db.commit()
    assert "duplicate_people" not in _kinds(run_checks(db))


# ── state ────────────────────────────────────────────────────────────────────
def test_it_finds_one_ev_held_by_two_people(db):
    a, b = make_person(db, "A"), make_person(db, "B")
    make_ev(db, "CBICEVD0250", provider="Raft", model="Blue", status="in_use")
    assign(db, a, "CBICEVD0250", handover="2026-09-01")
    assign(db, b, "CBICEVD0250", handover="2026-09-05")
    db.commit()
    assert len(_of(run_checks(db), "ev_held_twice")) == 1


@pytest.mark.parametrize(
    ("status", "held", "expect"),
    [
        ("spare", True, "still holding it"),
        ("in_use", False, "nobody holds it"),
        ("returned", False, None),
        ("in_use", True, None),
    ],
)
def test_status_and_assignment_must_agree(db, status, held, expect):
    make_ev(db, "CBICEVD0250", provider="Raft", model="Blue", status=status)
    if held:
        assign(db, make_person(db, "Holder"), "CBICEVD0250", handover="2026-09-01")
    # assign() sets the unit in_use, which is the correct pairing. Set the
    # status back afterwards: the case under test is precisely the one where
    # the two got out of step, which no well-behaved helper will produce.
    db.execute("UPDATE ev_units SET status=? WHERE ev_id='CBICEVD0250'", (status,))
    db.commit()
    hits = _of(run_checks(db), "ev_status_disagrees")
    if expect is None:
        assert hits == []
    else:
        assert expect in hits[0]["detail"]


# ── money ────────────────────────────────────────────────────────────────────
def test_it_finds_rent_charged_during_a_repair(db):
    pid = make_person(db, "Paid For A Bike In The Workshop")
    make_ev(db, "CBICEVD0250", provider="Raft", model="Blue", status="in_use")
    assign(db, pid, "CBICEVD0250", handover="2026-09-01")
    db.execute(
        "INSERT INTO ev_maintenance (ev_id, from_date, to_date, reason) "
        "VALUES ('CBICEVD0250', '2026-09-05', '2026-09-07', 'brakes')"
    )
    for day in ("2026-09-05", "2026-09-06"):
        db.execute(
            "INSERT INTO ev_daily_ledger (ev_id, day, state, assigned_person_id, daily_cost, "
            "provider_cost, billing_status) VALUES (?,?, 'billable', ?, 18500, 18500, 'billed')",
            ("CBICEVD0250", day, pid),
        )
    db.commit()
    hit = _of(run_checks(db), "billed_during_maintenance")
    assert len(hit) == 1
    assert hit[0]["amount"] == 37000
    assert hit[0]["severity"] == "money"


def test_a_free_day_during_a_repair_is_not_a_finding(db):
    """A zero-cost day is the maintenance window working, not failing."""
    pid = make_person(db, "Correctly Not Charged")
    make_ev(db, "CBICEVD0250", provider="Raft", model="Blue", status="in_use")
    assign(db, pid, "CBICEVD0250", handover="2026-09-01")
    db.execute(
        "INSERT INTO ev_maintenance (ev_id, from_date, to_date, reason) "
        "VALUES ('CBICEVD0250', '2026-09-05', '2026-09-07', 'brakes')"
    )
    db.execute(
        "INSERT INTO ev_daily_ledger (ev_id, day, state, assigned_person_id, daily_cost, "
        "provider_cost, billing_status) VALUES "
        "('CBICEVD0250', '2026-09-05', 'maintenance', ?, 0, 18500, 'waived')",
        (pid,),
    )
    db.commit()
    assert "billed_during_maintenance" not in _kinds(run_checks(db))


def test_it_finds_rent_on_somebody_who_never_had_an_ev(db):
    """The tail of a duplicate: the rent landed on one copy of the man and the
    vehicle on the other."""
    pid = make_person(db, "Phantom Half")
    make_rider(db, pid, "R-1", "Jiffy", "Phantom Half")
    db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after) VALUES (?,?, 'Jiffy', '2026-09-08','2026-09-14',"
        "'RENT', -129500, -129500)",
        (pid, "R-1"),
    )
    db.commit()
    hit = _of(run_checks(db), "rent_with_no_vehicle")
    assert len(hit) == 1
    assert hit[0]["person_ids"] == [pid]


# ── the page itself ──────────────────────────────────────────────────────────
def test_money_findings_come_first(db):
    a, b = make_person(db, "A"), make_person(db, "B")
    make_ev(db, "CBICEVD0250", provider="Raft", model="Blue", status="in_use")
    make_ev(db, "CBJCEVD0250", provider="Raft", model="Blue", status="spare")
    assign(db, a, "CBICEVD0250", handover="2026-09-01")
    make_rider(db, b, "R-1", "Jiffy", "B")
    db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after) VALUES (?,?, 'Jiffy','2026-09-08','2026-09-14',"
        "'RENT', -129500, -129500)",
        (b, "R-1"),
    )
    db.commit()
    findings = run_checks(db)
    assert findings[0]["severity"] == "money"
    assert "identity" in {f["severity"] for f in findings}


def test_one_broken_check_does_not_take_the_page_down(db, monkeypatch):
    from payout.domain import anomalies

    def explodes(_conn):
        raise RuntimeError("bad SQL")

    monkeypatch.setattr(anomalies, "CHECKS", (explodes, anomalies.ev_held_twice))
    a, b = make_person(db, "A"), make_person(db, "B")
    make_ev(db, "CBICEVD0250", provider="Raft", model="Blue", status="in_use")
    assign(db, a, "CBICEVD0250", handover="2026-09-01")
    assign(db, b, "CBICEVD0250", handover="2026-09-05")
    db.commit()
    findings = anomalies.run_checks(db)
    assert "ev_held_twice" in _kinds(findings)
    assert any("could not run" in f["title"] for f in findings)


# ── the recruiter board's quality columns ────────────────────────────────────
def test_the_board_separates_never_worked_from_stopped_working(db):
    """A headcount cannot tell a recruiter who brings in riders who leave from
    one who brings in riders who never start. The second is the failure worth
    catching early, and it looked identical to the first."""
    from datetime import date, timedelta

    from payout.api.routes.recruiters import NEVER_WORKED_GRACE_DAYS

    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) "
        "VALUES ('rec@t.test', 'x', 'recruiter', 1)"
    )
    old = (date.today() - timedelta(days=NEVER_WORKED_GRACE_DAYS + 10)).isoformat()
    fresh = date.today().isoformat()
    worked, never, too_new = (
        make_person(db, "Worked Once"),
        make_person(db, "Never Started"),
        make_person(db, "Onboarded Today"),
    )
    for pid, rid, when in (
        (worked, "R-1", old),
        (never, "R-2", old),
        (too_new, "R-3", fresh),
    ):
        make_rider(db, pid, rid, "Jiffy", "R")
        db.execute(
            "UPDATE rider_master SET recruited_by='rec@t.test', created_at=? WHERE rider_id=?",
            (when + " 09:00:00", rid),
        )
    db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after) VALUES (?, 'R-1', 'Jiffy', ?, ?, 'PAYOUT', 5000, 0)",
        (worked, old, old),
    )
    db.commit()

    from payout.api.routes.recruiters import recruiter_board

    row = recruiter_board(days=30, user={"email": "admin@t.test", "role": "admin"})["recruiters"][0]
    assert row["onboarded_all_time"] == 3
    # "Onboarded Today" is silent, not failing: no cycle has closed over them.
    assert row["never_worked"] == 1


def test_the_board_counts_a_recruiters_duplicates(db):
    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) "
        "VALUES ('rec@t.test', 'x', 'recruiter', 1)"
    )
    a, b = make_person(db, "SUSANTA GHOSH"), make_person(db, "Sushanta ghosh")
    make_rider(db, a, "R-1", "Jiffy", "SUSANTA GHOSH")
    make_rider(db, b, "R-2", "Myntra", "Sushanta ghosh")
    db.execute("UPDATE rider_master SET mob_no='7432856791', recruited_by='rec@t.test'")
    db.commit()

    from payout.api.routes.recruiters import recruiter_board

    row = recruiter_board(days=30, user={"email": "admin@t.test", "role": "admin"})["recruiters"][0]
    assert row["duplicates"] == 2
