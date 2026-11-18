import pytest

from payout.cycle_calendar import correct_cycle
from tests.conftest import make_person


def add_run(db, pid, start, end, amount=10000):
    db.execute(
        "INSERT INTO company_cycles (company,cycle_start,cycle_end,week_bucket) "
        "VALUES ('Myntra',?,?,'2026-W43')",
        (start, end),
    )
    db.execute(
        "INSERT INTO transactions (person_id,company,cycle_start,cycle_end,event_type,"
        "amount,balance_after) VALUES (?,'Myntra',?,?,'PAYOUT',?,0)",
        (pid, start, end, amount),
    )


def test_duplicate_exclusion_preserves_financial_state_and_later_entries(db):
    pid = make_person(db, balance=-12345, arrears=4321)
    add_run(db, pid, "2026-10-14", "2026-10-20")
    add_run(db, pid, "2026-10-21", "2026-10-21")
    before = [tuple(r) for r in db.execute("SELECT * FROM transactions ORDER BY id")]
    assert correct_cycle(
        db, "Myntra", "2026-10-21", "2026-10-21", duplicate_of=("2026-10-14", "2026-10-20")
    )
    assert [tuple(r) for r in db.execute("SELECT * FROM transactions ORDER BY id")] == before
    assert db.execute("SELECT COUNT(*) FROM reporting_transactions").fetchone()[0] == 1
    assert db.execute("SELECT current_balance FROM balances").fetchone()[0] == -12345
    assert db.execute("SELECT outstanding FROM ev_arrears").fetchone()[0] == 4321
    assert not correct_cycle(
        db, "Myntra", "2026-10-21", "2026-10-21", duplicate_of=("2026-10-14", "2026-10-20")
    )
    add_run(db, pid, "2026-10-21", "2026-10-21", 500)
    assert db.execute("SELECT SUM(amount) FROM reporting_transactions").fetchone()[0] == 10500


def test_date_repair_changes_reporting_and_next_cycle_only(db):
    from payout.api.routes.companies import get_next_cycle

    pid = make_person(db)
    add_run(db, pid, "2026-11-08", "2026-11-14")
    correct_cycle(db, "Myntra", "2026-11-08", "2026-11-14", ("2026-11-02", "2026-11-08"))
    assert db.execute("SELECT cycle_end FROM reporting_transactions").fetchone()[0] == "2026-11-08"
    assert db.execute("SELECT cycle_end FROM transactions").fetchone()[0] == "2026-11-14"
    db.commit()
    assert get_next_cycle("Myntra", {})["cycle_start"] == "2026-11-09"


def test_different_payout_is_not_removed(db):
    pid = make_person(db)
    add_run(db, pid, "2026-10-14", "2026-10-20")
    add_run(db, pid, "2026-10-21", "2026-10-21", 999)
    with pytest.raises(ValueError, match="do not match"):
        correct_cycle(
            db, "Myntra", "2026-10-21", "2026-10-21", duplicate_of=("2026-10-14", "2026-10-20")
        )
    assert db.execute("SELECT COUNT(*) FROM cycle_reporting_adjustments").fetchone()[0] == 0
