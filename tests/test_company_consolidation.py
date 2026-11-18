import pytest

from payout.company_consolidation import consolidate_blitz
from payout.db.seed import seed_companies
from tests.conftest import make_person, make_rider


def test_merge_preserves_money_and_unique_ids(db):
    pid = make_person(db, balance=-12345, arrears=6789)
    make_rider(db, pid, "SAME", "Kaptan")
    make_rider(db, pid, "SAME", "Nykaa")
    make_rider(db, pid, "OTHER", "Nykaa")
    db.execute("UPDATE person_registry SET deduction_company='Nykaa' WHERE person_id=?", (pid,))
    before = tuple(db.execute("SELECT * FROM balances WHERE person_id=?", (pid,)).fetchone())
    arrears = tuple(db.execute("SELECT * FROM ev_arrears WHERE person_id=?", (pid,)).fetchone())
    assert consolidate_blitz(db) == {"companies": 2, "duplicate_ids": 1}
    assert [
        r[0]
        for r in db.execute(
            "SELECT rider_id FROM rider_master WHERE company='Blitz' ORDER BY rider_id"
        )
    ] == ["OTHER", "SAME"]
    assert (
        tuple(db.execute("SELECT * FROM balances WHERE person_id=?", (pid,)).fetchone()) == before
    )
    assert (
        tuple(db.execute("SELECT * FROM ev_arrears WHERE person_id=?", (pid,)).fetchone())
        == arrears
    )
    assert (
        db.execute(
            "SELECT deduction_company FROM person_registry WHERE person_id=?", (pid,)
        ).fetchone()[0]
        == "Blitz"
    )
    seed_companies(db)
    assert (
        db.execute(
            "SELECT count(*) FROM companies WHERE company_name IN ('Kaptan','Nykaa')"
        ).fetchone()[0]
        == 0
    )
    assert consolidate_blitz(db) == {"companies": 0, "duplicate_ids": 0}


def test_conflicting_people_roll_back_entire_merge(db):
    make_rider(db, make_person(db), "SAME", "Kaptan")
    make_rider(db, make_person(db), "SAME", "Nykaa")
    with pytest.raises(ValueError, match="different people"):
        consolidate_blitz(db)
    assert db.execute("SELECT count(*) FROM rider_master WHERE company='Blitz'").fetchone()[0] == 0
    assert (
        db.execute("SELECT count(*) FROM companies WHERE company_name='Blitz'").fetchone()[0] == 0
    )
    assert db.execute("SELECT count(*) FROM rider_master").fetchone()[0] == 2


def test_dry_run_can_rollback(db):
    db.execute("BEGIN")
    consolidate_blitz(db)
    db.rollback()
    assert (
        db.execute("SELECT count(*) FROM companies WHERE company_name='Blitz'").fetchone()[0] == 0
    )


def test_placeholder_collision_keeps_people_separate(db):
    first, second = make_person(db), make_person(db)
    make_rider(db, first, "REAL", "Kaptan")
    make_rider(db, first, "QSPEND0001", "Nykaa")
    make_rider(db, second, "QSPEND0001", "Kaptan")
    consolidate_blitz(db)
    rows = [
        tuple(r)
        for r in db.execute(
            "SELECT rider_id,person_id FROM rider_master WHERE company='Blitz' ORDER BY rider_id"
        )
    ]
    assert rows == [("QSPEND0001", second), ("REAL", first)]
    assert db.execute("SELECT COUNT(*) FROM person_registry").fetchone()[0] == 2
