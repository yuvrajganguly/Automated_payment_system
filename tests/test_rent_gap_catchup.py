"""Regression for the 2026-09-04 rent-gap incident (Jeet Ghosh, person 581).

A rider works Spencer's 15-21, then Myntra 24-30, then Spencer's 22-31.
Before the fix each cycle billed only its own days: Myntra took 24-30 and
pushed the meter to the 30th, so the later Spencer's cycle (22-31) found the
meter past its start and billed the 31st alone.  The 22nd and 23rd were never
charged and nothing would ever charge them.

Now a cycle reaches back over unaccounted days behind the meter, so Myntra
bills 22-30 (two catch-up days + its own seven) and Spencer's bills the 31st.
Every held day 16..31 (the handover day is free) is billed exactly once and the day-ledger says so.
"""

import io
from datetime import date

from openpyxl import Workbook

from payout.domain.engine import process_cycle
from tests.conftest import assign, make_ev, make_person, make_rider

DAY = 18000  # Blive Standard: 126000 paise / week


def _file(rows, headers=("rider_id", "net_pay")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _myntra(rows):
    return _file(rows, headers=("Worker Code", "Final Payout", "COD-Pending"))


def _setup(db):
    pid = make_person(db, "Jeet", balance=0, arrears=0)
    make_rider(db, pid, "S1", "Blitz", "Jeet")
    make_rider(db, pid, "M1", "Myntra", "Jeet")
    make_ev(db, "EV1", status="in_use")
    assign(db, pid, "EV1", handover="2026-08-15")
    db.commit()
    return pid


def _rent_rows(db, pid):
    return db.execute(
        "SELECT company, cycle_start, cycle_end, days, -amount AS debit "
        "FROM transactions WHERE person_id=? AND event_type='RENT' ORDER BY id",
        (pid,),
    ).fetchall()


def test_days_between_two_companies_cycles_are_not_written_off(db):
    pid = _setup(db)

    # Spencer's 15-21 (stand-in company: Blitz, same generic parser).
    r1 = process_cycle(
        "Blitz", date(2026, 8, 15), date(2026, 8, 21), _file([("S1", 5000)]), commit=True
    )
    # Myntra 24-30 processed next: the meter sits at the 21st, 22-23 are owed.
    r2 = process_cycle(
        "Myntra", date(2026, 8, 24), date(2026, 8, 30), _myntra([("M1", 5000, 0)]), commit=True
    )
    # Spencer's 22-31 arrives last; only the 31st is still unbilled.
    r3 = process_cycle(
        "Blitz", date(2026, 8, 22), date(2026, 8, 31), _file([("S1", 5000)]), commit=True
    )

    rows = _rent_rows(db, pid)
    assert [(r["company"], r["days"], r["debit"]) for r in rows] == [
        ("Blitz", 6, 6 * DAY),  # 16-21 (handover day itself is free)
        ("Myntra", 9, 9 * DAY),  # 22-23 caught up + 24-30
        ("Blitz", 1, 1 * DAY),  # 31 only
    ]
    assert sum(r["days"] for r in rows) == 16  # 16..31, once each

    # The catch-up is announced, not silent.
    assert any("catch-up" in w.lower() for w in r2.warnings), r2.warnings
    assert not any("catch-up" in w.lower() for w in r1.warnings + r3.warnings)

    # Day-ledger: every held day billed, the two gap days included.
    led = {
        r["day"]: r["billing_status"]
        for r in db.execute(
            "SELECT day, billing_status FROM ev_daily_ledger WHERE ev_id='EV1' ORDER BY day"
        )
    }
    assert led["2026-08-22"] == "billed" and led["2026-08-23"] == "billed"
    assert all(led.get(f"2026-08-{d:02d}") == "billed" for d in range(16, 32)), led
    # Handover day itself is free.
    assert led.get("2026-08-15") != "billed"
    assert (
        db.execute("SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()[
            "outstanding"
        ]
        == 0
    )


def test_gap_already_missed_to_arrears_is_not_billed_twice(db):
    """Same shape, but the 22-23 gap was already put in arrears by the
    back-rent flow (RENT_MISSED window): Myntra must bill only its own week."""
    pid = _setup(db)
    process_cycle("Blitz", date(2026, 8, 15), date(2026, 8, 21), _file([("S1", 5000)]), commit=True)
    db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, days) "
        "VALUES (?, 'S1', 'Blitz', '2026-08-22', '2026-08-23', 'RENT_MISSED', ?, 0, 2)",
        (pid, -2 * DAY),
    )
    db.commit()
    r2 = process_cycle(
        "Myntra", date(2026, 8, 24), date(2026, 8, 30), _myntra([("M1", 5000, 0)]), commit=True
    )
    rows = _rent_rows(db, pid)
    assert [(r["company"], r["days"]) for r in rows] == [("Blitz", 6), ("Myntra", 7)]
    assert not any("catch-up" in w.lower() for w in r2.warnings)


def test_scan_and_apply_unbilled_days_for_pre_fix_data(db):
    """Production data written before the fix: Myntra already billed 24-30
    with the meter at the 30th, 22-23 have ledger rows without a status.
    The sweep reports exactly those two days and --apply books them once."""
    from payout.domain.unbilled import apply_unbilled, scan_unbilled

    pid = _setup(db)
    process_cycle("Blitz", date(2026, 8, 15), date(2026, 8, 21), _file([("S1", 5000)]), commit=True)
    # Simulate the old engine: Myntra billed only its own week, meter -> 30.
    db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, days) "
        "VALUES (?, 'M1', 'Myntra', '2026-08-24', '2026-08-30', 'RENT', ?, 0, 7)",
        (pid, -7 * DAY),
    )
    db.execute(
        "UPDATE ev_assignments SET rent_charged_through='2026-08-30' WHERE person_id=?", (pid,)
    )
    for d in (22, 23):
        db.execute(
            "INSERT INTO ev_daily_ledger (ev_id, day, state, assigned_person_id, daily_cost, "
            "provider_cost) VALUES ('EV1', ?, 'billable', ?, ?, ?)",
            (f"2026-08-{d}", pid, DAY, DAY),
        )
    db.commit()

    found = scan_unbilled(db, today=date(2026, 9, 4))
    assert [(f["person_id"], f["runs"]) for f in found] == [
        (pid, [{"from": "2026-08-22", "to": "2026-08-23", "days": 2, "amount": 2 * DAY}])
    ]

    amt = apply_unbilled(db, person_id=pid, ev_id="EV1", day_from="2026-08-22", day_to="2026-08-23")
    db.commit()
    assert amt == 2 * DAY
    assert (
        db.execute("SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()[
            "outstanding"
        ]
        == 2 * DAY
    )
    led = {
        r["day"]: r["billing_status"]
        for r in db.execute("SELECT day, billing_status FROM ev_daily_ledger WHERE ev_id='EV1'")
    }
    assert led["2026-08-22"] == "missed" and led["2026-08-23"] == "missed"
    # Idempotent: nothing left to report, and a second apply is refused.
    assert scan_unbilled(db, today=date(2026, 9, 4)) == []
    assert (
        apply_unbilled(db, person_id=pid, ev_id="EV1", day_from="2026-08-22", day_to="2026-08-23")
        == 0
    )
    # The next payout claws the arrears back the normal way.
    process_cycle("Blitz", date(2026, 8, 22), date(2026, 8, 31), _file([("S1", 5000)]), commit=True)
    assert (
        db.execute("SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()[
            "outstanding"
        ]
        == 0
    )
    rec = db.execute(
        "SELECT SUM(amount) FROM transactions WHERE person_id=? AND event_type='RENT_RECOVERED'",
        (pid,),
    ).fetchone()[0]
    assert rec == 2 * DAY


def test_set_last_billed_day_marks_gap_accounted_and_blocks_catchup(db):
    """POST /persons/{id}/rent-meter: the meter moves forward, the days in
    between get 'waived' day-rows + a RENT_WAIVED audit row, and neither the
    next cycle's catch-up nor the sweep raises them again. Forward only."""
    from datetime import date as _date

    from payout.domain.unbilled import scan_unbilled
    from tests.test_deposit import _client

    pid = _setup(db)
    process_cycle("Blitz", date(2026, 8, 15), date(2026, 8, 21), _file([("S1", 5000)]), commit=True)
    c = _client(db)
    r = c.post(
        f"/api/persons/{pid}/rent-meter",
        json={"through": "2026-08-23", "reason": "paid the owner in cash"},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {
        "person_id": pid,
        "ev_id": "EV1",
        "rent_charged_through": "2026-08-23",
        "previous": "2026-08-21",
        "days_waived": 2,
        "transaction_id": r.json()["transaction_id"],
    }
    led = {
        x["day"]: x["billing_status"]
        for x in db.execute("SELECT day, billing_status FROM ev_daily_ledger WHERE ev_id='EV1'")
    }
    assert led["2026-08-22"] == "waived" and led["2026-08-23"] == "waived"
    tx = db.execute(
        "SELECT amount, days, cycle_start, cycle_end FROM transactions "
        "WHERE person_id=? AND event_type='RENT_WAIVED'",
        (pid,),
    ).fetchone()
    assert (tx["amount"], tx["days"], tx["cycle_start"], tx["cycle_end"]) == (
        0,
        2,
        "2026-08-22",
        "2026-08-23",
    )
    # Backwards is refused.
    r = c.post(f"/api/persons/{pid}/rent-meter", json={"through": "2026-08-20", "reason": "x"})
    assert r.status_code == 400
    # Myntra 24-30 now finds nothing to catch up; the sweep is clean.
    res = process_cycle(
        "Myntra", date(2026, 8, 24), date(2026, 8, 30), _myntra([("M1", 5000, 0)]), commit=True
    )
    assert not [w for w in res.warnings if "catch-up" in w.lower()]
    last = _rent_rows(db, pid)[-1]
    assert (last["company"], last["days"]) == ("Myntra", 7)
    assert scan_unbilled(db, today=_date(2026, 9, 4)) == []
    # Arrears untouched: nothing was owed, nothing was added.
    assert (
        db.execute("SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()
        or {"outstanding": 0}
    )["outstanding"] == 0
