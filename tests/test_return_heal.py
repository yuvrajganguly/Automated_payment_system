"""Backdated EV return healing (domain/return_heal.py + /evs endpoints).

The story under test: the office learns late that an EV went back on date R.
Every rent charge for days >= R must be reversed mechanically — refunds for
days the rider actually paid, write-offs for days that fell to arrears — with
offsetting audit rows, a rewritten day-ledger, and a rewound rent meter.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from openpyxl import Workbook

from payout.domain.engine import process_cycle
from tests.conftest import assign, make_ev, make_person, make_rider

WEEK = 125000  # paise


def _file(rows, headers=("rider_id", "net_pay")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _client(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("adm@t.test", hash_password("Admin-pass-1"), "admin"),
    )
    db.commit()
    ratelimit.reset()
    c = TestClient(app)
    c.__enter__()
    assert (
        c.post(
            "/api/auth/login", data={"username": "adm@t.test", "password": "Admin-pass-1"}
        ).status_code
        == 200
    )
    return c


def _ledger_cost(db, ev_id, day_from):
    row = db.execute(
        "SELECT COALESCE(SUM(daily_cost),0) FROM ev_daily_ledger "
        "WHERE ev_id=? AND day >= ? AND billing_status IS NOT NULL",
        (ev_id, day_from.isoformat()),
    ).fetchone()
    return int(row[0])


def _balance(db, pid):
    r = db.execute("SELECT current_balance FROM balances WHERE person_id=?", (pid,)).fetchone()
    return int(r[0]) if r else 0


def _outstanding(db, pid):
    r = db.execute("SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()
    return int(r[0]) if r else 0


def _seed(db, rid, ev_id, wk_start):
    pid = make_person(db, f"R-{rid}", balance=0, arrears=0)
    make_rider(db, pid, rid, "Blitz", f"R-{rid}")
    make_ev(db, ev_id, provider="Raft", model="Regular")
    assign(db, pid, ev_id, charged_through=(wk_start - timedelta(days=1)).isoformat())
    db.execute(
        "UPDATE person_registry SET deduction_company='Blitz', deduction_rider_id=? "
        "WHERE person_id=?",
        (rid, pid),
    )
    db.commit()
    return pid


def test_backdated_return_refunds_billed_days(db):
    """Rider PAID a full week via payout; EV actually left mid-week."""
    wk = date(2026, 6, 1)  # Monday
    pid = _seed(db, "H1", "EV-H", wk)
    process_cycle("Blitz", wk, wk + timedelta(days=6), _file([("H1", 5000)]), commit=True)
    bal_before = _balance(db, pid)
    ret = wk + timedelta(days=4)  # Friday — Fri/Sat/Sun were wrongly charged
    expected_refund = _ledger_cost(db, "EV-H", ret)
    assert expected_refund > 0

    c = _client(db)
    r = c.post("/api/evs/return", json={"ev_id": "EV-H", "returned_date": ret.isoformat()})
    assert r.status_code == 200, r.text
    heal = r.json()["heal"]
    assert heal["refunded"] == expected_refund / 100  # rupees at the edge
    assert heal["arrears_written_off"] == 0
    assert heal["days_reversed"] == 3

    assert _balance(db, pid) == bal_before + expected_refund
    # audit: offsetting ADJUSTMENT, history untouched
    adj = db.execute(
        "SELECT amount, remarks FROM transactions WHERE person_id=? AND event_type='ADJUSTMENT'",
        (pid,),
    ).fetchone()
    assert adj["amount"] == expected_refund and "EV-H" in adj["remarks"]
    # ledger: return day free, later days gone (unit retired), meter rewound
    ret_row = db.execute(
        "SELECT state, daily_cost FROM ev_daily_ledger WHERE ev_id='EV-H' AND day=?",
        (ret.isoformat(),),
    ).fetchone()
    assert ret_row["state"] == "return_free" and ret_row["daily_cost"] == 0
    assert (
        db.execute(
            "SELECT COUNT(*) FROM ev_daily_ledger WHERE ev_id='EV-H' AND day > ?",
            (ret.isoformat(),),
        ).fetchone()[0]
        == 0
    )
    meter = db.execute(
        "SELECT rent_charged_through FROM ev_assignments WHERE person_id=?", (pid,)
    ).fetchone()[0]
    assert meter == (ret - timedelta(days=1)).isoformat()


def test_backdated_return_writes_off_missed_days(db):
    """Rider ABSENT; the whole week fell to arrears — but the EV was returned
    before the week began, so the debt is written off, not kept."""
    wk = date(2026, 6, 1)
    pid = _seed(db, "H2", "EV-M", wk)
    process_cycle("Blitz", wk, wk + timedelta(days=6), _file([("OTHER", 10)]), commit=True)
    assert _outstanding(db, pid) == WEEK

    c = _client(db)
    r = c.post("/api/evs/return", json={"ev_id": "EV-M", "returned_date": wk.isoformat()})
    assert r.status_code == 200, r.text
    heal = r.json()["heal"]
    assert heal["arrears_written_off"] == WEEK / 100
    assert heal["refunded"] == 0
    assert _outstanding(db, pid) == 0
    assert _balance(db, pid) == 0
    row = db.execute(
        "SELECT amount, days FROM transactions WHERE person_id=? AND event_type='RENT_REVERSAL'",
        (pid,),
    ).fetchone()
    assert row["amount"] == WEEK and row["days"] == 7
    tm = db.execute("SELECT total_missed FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()[0]
    assert tm == 0


def test_to_spare_keeps_provider_cost(db):
    """Take-back-to-spare: rider days become 'unassigned' but we still owe the
    provider for a unit we hold."""
    wk = date(2026, 6, 1)
    _seed(db, "H3", "EV-S", wk)
    process_cycle("Blitz", wk, wk + timedelta(days=6), _file([("H3", 5000)]), commit=True)
    ret = wk + timedelta(days=3)
    c = _client(db)
    r = c.post("/api/evs/to-spare", json={"ev_id": "EV-S", "returned_date": ret.isoformat()})
    assert r.status_code == 200, r.text
    assert r.json()["heal"]["days_reversed"] == 4  # Thu..Sun
    rows = db.execute(
        "SELECT state, assigned_person_id, daily_cost, provider_cost FROM ev_daily_ledger "
        "WHERE ev_id='EV-S' AND day > ? ORDER BY day",
        (ret.isoformat(),),
    ).fetchall()
    assert len(rows) == 3
    for row in rows:
        assert row["state"] == "unassigned" and row["assigned_person_id"] is None
        assert row["daily_cost"] == 0 and row["provider_cost"] > 0


def test_amend_return_heals_and_validates(db):
    """Return recorded late with today's date, then corrected backwards."""
    wk = date(2026, 6, 1)
    pid = _seed(db, "H4", "EV-A", wk)
    process_cycle("Blitz", wk, wk + timedelta(days=6), _file([("H4", 5000)]), commit=True)
    c = _client(db)
    # Returned "today" (after the cycle) — nothing to heal yet.
    late = wk + timedelta(days=10)
    r = c.post("/api/evs/return", json={"ev_id": "EV-A", "returned_date": late.isoformat()})
    assert r.status_code == 200 and r.json()["heal"]["days_reversed"] == 0
    # Amend to the true date, mid-cycle: the wrongly-paid tail comes back.
    true_ret = wk + timedelta(days=4)
    expected_refund = _ledger_cost(db, "EV-A", true_ret)
    r = c.post(
        "/api/evs/amend-return", json={"ev_id": "EV-A", "returned_date": true_ret.isoformat()}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["previous_date"] == late.isoformat()
    assert body["heal"]["refunded"] == expected_refund / 100
    assert _balance(db, pid) == expected_refund
    # Amending forwards is refused.
    r = c.post("/api/evs/amend-return", json={"ev_id": "EV-A", "returned_date": late.isoformat()})
    assert r.status_code == 400
    # Unknown EV.
    r = c.post("/api/evs/amend-return", json={"ev_id": "NOPE", "returned_date": "2026-06-01"})
    assert r.status_code == 404


def test_refund_offsets_remaining_arrears(db):
    """Refund lands on a rider who STILL owes other arrears -> the standard
    credit-vs-arrears offset consumes it instead of leaving both sides open."""
    wk = date(2026, 6, 1)
    pid = _seed(db, "H5", "EV-O", wk)
    # Pre-existing unrelated arrears (e.g. from an earlier EV).
    db.execute(
        "UPDATE ev_arrears SET total_missed=40000, outstanding=40000 WHERE person_id=?",
        (pid,),
    )
    db.execute(
        "INSERT OR IGNORE INTO ev_arrears (person_id, total_missed, total_recovered, outstanding) "
        "VALUES (?, 40000, 0, 40000)",
        (pid,),
    )
    db.commit()
    process_cycle("Blitz", wk, wk + timedelta(days=6), _file([("H5", 8000)]), commit=True)
    # The cycle recovered the 40k arrears too; put fresh ones back to test the offset.
    db.execute("UPDATE ev_arrears SET outstanding=30000 WHERE person_id=?", (pid,))
    db.commit()
    bal_before = _balance(db, pid)
    ret = wk + timedelta(days=4)
    expected_refund = _ledger_cost(db, "EV-O", ret)
    c = _client(db)
    r = c.post("/api/evs/return", json={"ev_id": "EV-O", "returned_date": ret.isoformat()})
    assert r.status_code == 200, r.text
    heal = r.json()["heal"]
    offset = int(heal["offset_applied"] * 100)
    assert offset == min(max(0, bal_before + expected_refund), 30000)
    assert _outstanding(db, pid) == 30000 - offset
    assert _balance(db, pid) == bal_before + expected_refund - offset
