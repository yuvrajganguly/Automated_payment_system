from datetime import date

from payout.domain.holds import compute_holds, persist_holds
from payout.domain.models import CodHoldLine, ParseResult, RiderRecord


def test_jiffy_sum_per_worker():
    pr = ParseResult(
        company="Jiffy",
        records=[RiderRecord("J1", 500), RiderRecord("J2", 600)],
        cod_lines=[
            CodHoldLine("J1", 100, txn_status="Pending"),
            CodHoldLine("J1", 50, txn_status="Pending"),
            CodHoldLine("J2", 200, txn_status="Pending"),
        ],
    )
    h = compute_holds(pr)
    assert h.per_rider == {"J1": 150.0, "J2": 200.0}
    assert h.held_rider_ids == {"J1", "J2"}
    assert h.total == 350.0
    assert h.skipped_nonpending == 0


def test_jiffy_skips_non_pending():
    pr = ParseResult(
        company="Jiffy",
        records=[],
        cod_lines=[
            CodHoldLine("J1", 100, txn_status="Pending"),
            CodHoldLine("J1", 80, txn_status="Settled"),
        ],
    )
    h = compute_holds(pr)
    assert h.per_rider == {"J1": 100.0}
    assert h.skipped_nonpending == 1


def test_blank_status_counts_as_pending():
    pr = ParseResult(
        company="Jiffy",
        records=[],
        cod_lines=[CodHoldLine("J1", 100, txn_status=None), CodHoldLine("J2", 50, txn_status="")],
    )
    assert compute_holds(pr).per_rider == {"J1": 100.0, "J2": 50.0}


def test_myntra_inline_column():
    pr = ParseResult(
        company="Myntra",
        records=[RiderRecord("M1", 1200, cod_pending=0.0), RiderRecord("M2", 800, cod_pending=150.0)],
    )
    h = compute_holds(pr)
    assert h.per_rider == {"M2": 150.0}
    assert h.held_rider_ids == {"M2"}


def test_persist_holds(db):
    pid = db.execute("INSERT INTO person_registry (display_name) VALUES ('R')").lastrowid
    db.execute("INSERT INTO rider_master (rider_id, company, person_id, name) VALUES ('J1','Jiffy',?,'R')", (pid,))
    db.commit()
    h = compute_holds(
        ParseResult(
            company="Jiffy",
            records=[],
            cod_lines=[
                CodHoldLine("J1", 100, order_number="O1", txn_status="Pending"),
                CodHoldLine("J1", 50, order_number="O2", txn_status="Pending"),
            ],
        )
    )
    persist_holds(db, "Jiffy", date(2026, 3, 2), date(2026, 3, 8), h)
    db.commit()
    rows = db.execute("SELECT person_id, amount, source FROM cod_holds WHERE company='Jiffy'").fetchall()
    assert len(rows) == 2
    assert all(r["person_id"] == pid and r["source"] == "jiffy_sheet" for r in rows)
    assert sum(r["amount"] for r in rows) == 150.0
