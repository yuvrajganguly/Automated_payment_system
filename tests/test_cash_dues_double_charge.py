"""Cash taken for Total Dues must not be taken again as Dues Cleared.

The incident (reported 2026-11-24): a rider owing EV arrears *and* carried
dues paid the Total Dues the console and the app show them (arrears + dues) in
cash. ``POST /ledger/rent-payment`` paid the arrears down, booked the rest as
RENT_COLLECTED, and left the negative balance where it was. The next payout
then cleared those same dues from the rider's earnings — "Dues Cleared" —
so the dues portion was charged twice: once in cash, once from the payout.

The rule these tests pin: a cash payment settles what the rider owes in the
same order the payout does — EV arrears, then carried dues — and only what is
left over counts as rent paid in advance.
"""

from __future__ import annotations

import io
from datetime import date

from openpyxl import Workbook

from payout.domain.engine import process_cycle
from tests.conftest import make_person, make_rider
from tests.test_rent_due import _hdr, client  # noqa: F401  (fixture)

WEEK = (date(2026, 11, 9), date(2026, 11, 15))


def _file(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["rider_id", "rider_name", "hub", "total_del", "net_pay"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _owing(db):
    """₹500 EV arrears + ₹300 carried dues = ₹800 Total Dues."""
    pid = make_person(db, "Owes Both", balance=-30_000, arrears=50_000)
    make_rider(db, pid, "40001", "Kaptan", "Owes Both")
    db.commit()
    return pid


def _state(db, pid):
    bal = db.execute("SELECT current_balance FROM balances WHERE person_id=?", (pid,)).fetchone()
    arr = db.execute("SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()
    return int(bal["current_balance"]), int(arr["outstanding"])


def test_paying_total_dues_in_cash_clears_both_buckets(db, client):  # noqa: F811
    pid = _owing(db)
    r = client.post(
        "/api/ledger/rent-payment",
        json={"person_id": pid, "amount": 800, "paid_on": "2026-11-12"},
        headers=_hdr(client),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied_to_arrears"] == 500
    assert body["applied_to_dues"] == 300
    assert body["applied_to_rent"] == 0
    assert _state(db, pid) == (0, 0)
    cleared = db.execute(
        "SELECT amount, balance_after FROM transactions "
        "WHERE person_id=? AND event_type='DUES_CLEARED'",
        (pid,),
    ).fetchall()
    assert [(c["amount"], c["balance_after"]) for c in cleared] == [(30_000, 0)]


def test_the_next_payout_does_not_take_the_same_dues_again(db, client):  # noqa: F811
    pid = _owing(db)
    client.post(
        "/api/ledger/rent-payment",
        json={"person_id": pid, "amount": 800, "paid_on": "2026-11-12"},
        headers=_hdr(client),
    )
    res = process_cycle(
        "Kaptan", *WEEK, _file([["40001", "Owes Both", "H", 10, 1000]]), commit=True
    )
    assert res.committed
    (row,) = res.pay_rows
    assert row.dues_cleared == 0
    assert row.arrears_recovered == 0
    assert row.released == 100_000  # the whole ₹1,000 — nothing owed any more


def test_a_part_payment_goes_arrears_first_then_dues(db, client):  # noqa: F811
    pid = _owing(db)
    r = client.post(
        "/api/ledger/rent-payment",
        json={"person_id": pid, "amount": 650, "paid_on": "2026-11-12"},
        headers=_hdr(client),
    ).json()
    assert (r["applied_to_arrears"], r["applied_to_dues"], r["applied_to_rent"]) == (500, 150, 0)
    assert _state(db, pid) == (-15_000, 0)
    # and the payout clears only the ₹150 still owed
    res = process_cycle(
        "Kaptan", *WEEK, _file([["40001", "Owes Both", "H", 10, 1000]]), commit=True
    )
    (row,) = res.pay_rows
    assert row.dues_cleared == 15_000 and row.released == 85_000


def test_money_beyond_the_debt_is_still_rent_paid_in_advance(db, client):  # noqa: F811
    pid = _owing(db)
    r = client.post(
        "/api/ledger/rent-payment",
        json={"person_id": pid, "amount": 1000, "paid_on": "2026-11-12"},
        headers=_hdr(client),
    ).json()
    assert (r["applied_to_arrears"], r["applied_to_dues"], r["applied_to_rent"]) == (500, 300, 200)
    assert _state(db, pid) == (0, 0)
