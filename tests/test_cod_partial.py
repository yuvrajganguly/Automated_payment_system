"""COD can be paid in parts.

A rider holding ₹1,500 of COD across two cycles hands over ₹1,000 now and the
rest next week. The office records each payment; the money goes oldest cycle
first, an entry closes only when it is fully paid, and "pending" everywhere is
what is still owed rather than what was held.
"""

from __future__ import annotations

from datetime import date

import pytest

from payout.domain.holds import (
    CodPaymentError,
    HoldLine,
    HoldResult,
    apply_cod_payment,
    persist_holds,
)
from tests.conftest import make_person, make_rider
from tests.test_rent_due import _hdr, client  # noqa: F401  (fixture)


def _cod(db, pid, rid, cs, ce, amount, order):
    return db.execute(
        "INSERT INTO cod_holds (cycle_start, cycle_end, company, rider_id, person_id, "
        "order_number, amount, source) VALUES (?,?,?,?,?,?,?,'jiffy_sheet')",
        (cs, ce, "Kaptan", rid, pid, order, amount),
    ).lastrowid


@pytest.fixture
def holder(db):
    pid = make_person(db, "Cod Holder")
    make_rider(db, pid, "50001", "Kaptan", "Cod Holder")
    old = _cod(db, pid, "50001", "2026-11-02", "2026-11-08", 60_000, "A1")
    new = _cod(db, pid, "50001", "2026-11-09", "2026-11-15", 90_000, "B1")
    db.commit()
    return pid, old, new


def _row(db, eid):
    return db.execute("SELECT paid, cleared_at FROM cod_holds WHERE id=?", (eid,)).fetchone()


def test_a_part_payment_goes_oldest_first_and_leaves_the_rest_owed(db, holder):
    pid, old, new = holder
    out = apply_cod_payment(db, pid, 100_000, paid_on="2026-11-20", created_by="t@t")
    assert out["cod_still_owed"] == 50_000
    assert (out["entries_cleared"], out["entries_touched"]) == (1, 2)
    assert _row(db, old)["paid"] == 60_000 and _row(db, old)["cleared_at"] == "2026-11-20"
    assert _row(db, new)["paid"] == 40_000 and _row(db, new)["cleared_at"] is None


def test_the_second_payment_closes_it(db, holder):
    pid, _old, new = holder
    apply_cod_payment(db, pid, 100_000, paid_on="2026-11-20", created_by="t@t")
    out = apply_cod_payment(db, pid, 50_000, paid_on="2026-11-27", created_by="t@t")
    assert out["cod_still_owed"] == 0
    assert _row(db, new)["cleared_at"] == "2026-11-27"
    assert (
        db.execute("SELECT COUNT(*) FROM cod_payments WHERE person_id=?", (pid,)).fetchone()[0] == 2
    )


def test_more_than_is_owed_is_refused(db, holder):
    pid, *_ = holder
    with pytest.raises(CodPaymentError):
        apply_cod_payment(db, pid, 150_001, paid_on="2026-11-20", created_by="t@t")
    assert db.execute("SELECT COUNT(*) FROM cod_payments").fetchone()[0] == 0


def test_rerunning_the_cycle_does_not_uncollect_cash(db, holder):
    """persist_holds rewrites a cycle's rows on a forced re-run. What was
    already collected must come through the rewrite."""
    pid, _old, _new = holder
    apply_cod_payment(db, pid, 100_000, paid_on="2026-11-20", created_by="t@t")
    persist_holds(
        db,
        "Kaptan",
        date(2026, 11, 9),
        date(2026, 11, 15),
        HoldResult(
            lines=[
                HoldLine(rider_id="50001", order_number="B1", amount=90_000, source="jiffy_sheet")
            ]
        ),
    )
    row = db.execute(
        "SELECT paid, cleared_at FROM cod_holds WHERE cycle_end='2026-11-15'"
    ).fetchone()
    assert row["paid"] == 40_000 and row["cleared_at"] is None


def test_over_http_the_page_shows_what_is_still_owed(db, client, holder):  # noqa: F811
    pid, *_ = holder
    h = _hdr(client)
    assert client.get("/api/cod", headers=h).json()[0]["total_pending"] == 1500.0
    r = client.post("/api/cod/pay", json={"person_id": pid, "amount": 1000}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["cod_still_owed"] == 500.0
    (row,) = client.get("/api/cod", headers=h).json()
    # paid so far on the entries still open (the ₹600 one closed)
    assert row["total_pending"] == 500.0 and row["total_cod_paid"] == 400.0
    entries = client.get(f"/api/cod/{pid}/entries", headers=h).json()
    open_one = next(e for e in entries if e["cleared_at"] is None)
    assert (open_one["amount"], open_one["cod_paid"], open_one["pending"]) == (900.0, 400.0, 500.0)
    too_much = client.post("/api/cod/pay", json={"person_id": pid, "amount": 600}, headers=h)
    assert too_much.status_code == 400
    assert len(client.get(f"/api/cod/{pid}/payments", headers=h).json()) == 1
