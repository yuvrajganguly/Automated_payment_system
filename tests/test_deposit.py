"""Security-deposit auto-clear on EV closure (₹2,700 cap).

When a rider's EV is closed, up to ₹2,700 comes off what they owe — EV
back-rent first, then carried dues — as DEPOSIT_APPLIED audit rows. Only the
surplus stays owed (and keeps them dormant / held). Damage charges are a
future feature; the deposit remainder stays outside the books.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from openpyxl import Workbook

from payout.domain.arrears import settle_from_deposit
from payout.domain.engine import process_cycle
from tests.conftest import assign, make_ev, make_person, make_rider

CAP = 270000  # paise


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


def _out(db, pid):
    r = db.execute("SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()
    return int(r[0]) if r else 0


def _bal(db, pid):
    r = db.execute("SELECT current_balance FROM balances WHERE person_id=?", (pid,)).fetchone()
    return int(r[0]) if r else 0


def test_deposit_covers_small_debt_entirely(db):
    """Owes less than the cap: everything clears, nothing credited beyond."""
    pid = make_person(db, "Small", balance=0, arrears=200000)
    db.commit()
    assert settle_from_deposit(db, pid, created_by="t") == 200000
    assert _out(db, pid) == 0
    assert _bal(db, pid) == 0, "leftover deposit must NOT become credit"
    ev = db.execute(
        "SELECT SUM(amount) FROM transactions WHERE person_id=? AND event_type='DEPOSIT_APPLIED'",
        (pid,),
    ).fetchone()[0]
    assert ev == 200000


def test_deposit_spills_into_general_dues(db):
    """₹1,000 arrears + ₹2,000 dues: cap clears arrears then ₹1,700 of dues."""
    pid = make_person(db, "Spill", balance=-200000, arrears=100000)
    db.commit()
    assert settle_from_deposit(db, pid, created_by="t") == CAP
    assert _out(db, pid) == 0
    assert _bal(db, pid) == -(200000 - 170000)  # ₹300 of dues left


def test_deposit_caps_at_2700(db):
    pid = make_person(db, "Big", balance=0, arrears=500000)
    db.commit()
    assert settle_from_deposit(db, pid, created_by="t") == CAP
    assert _out(db, pid) == 500000 - CAP


def test_return_applies_deposit_and_small_debtors_stop_being_dormant(db):
    """Absent one week (₹1,250 < cap) then EV returned late: the heal writes
    off nothing (return date after the cycle), the deposit clears the debt,
    and the rider is NOT dormant — future payouts flow normally."""
    wk = date(2026, 6, 1)
    pid = make_person(db, "SmallDebt", balance=0, arrears=0)
    make_rider(db, pid, "D1", "Blitz", "SmallDebt")
    make_ev(db, "EV-D1", provider="Raft", model="Regular")
    assign(db, pid, "EV-D1", charged_through="2026-05-31")
    db.execute(
        "UPDATE person_registry SET deduction_company='Blitz', deduction_rider_id='D1' "
        "WHERE person_id=?",
        (pid,),
    )
    db.commit()
    process_cycle("Blitz", wk, date(2026, 6, 7), _file([("X", 10)]), commit=True)
    assert _out(db, pid) == 125000

    c = _client(db)
    r = c.post("/api/evs/return", json={"ev_id": "EV-D1", "returned_date": "2026-06-08"})
    assert r.status_code == 200, r.text
    assert r.json()["heal"]["deposit_applied"] == 1250.0  # rupees at the edge
    assert _out(db, pid) == 0
    # Not dormant any more: a future payout is NOT held.
    r2 = process_cycle(
        "Blitz", date(2026, 6, 8), date(2026, 6, 14), _file([("D1", 2000)]), commit=True
    )
    row = (r2.pay_rows + r2.dues_rows)[0]
    assert row.is_hold is False


def test_return_with_big_debt_keeps_surplus_dormant(db):
    """Two absent weeks + prior arrears (₹5,250 total > cap): deposit knocks
    off ₹2,700, the surplus stays owed and the rider stays dormant-held."""
    wk = date(2026, 6, 1)
    pid = make_person(db, "BigDebt", balance=0, arrears=275000)
    make_rider(db, pid, "D2", "Blitz", "BigDebt")
    make_ev(db, "EV-D2", provider="Raft", model="Regular")
    assign(db, pid, "EV-D2", charged_through="2026-05-31")
    db.execute(
        "UPDATE person_registry SET deduction_company='Blitz', deduction_rider_id='D2' "
        "WHERE person_id=?",
        (pid,),
    )
    db.commit()
    process_cycle("Blitz", wk, date(2026, 6, 7), _file([("X", 10)]), commit=True)
    assert _out(db, pid) == 275000 + 125000

    c = _client(db)
    r = c.post("/api/evs/return", json={"ev_id": "EV-D2", "returned_date": "2026-06-08"})
    assert r.status_code == 200, r.text
    assert r.json()["heal"]["deposit_applied"] == 2700.0
    assert _out(db, pid) == 275000 + 125000 - CAP
    # Still dormant: future payout held untouched.
    r2 = process_cycle(
        "Blitz", date(2026, 6, 8), date(2026, 6, 14), _file([("D2", 2000)]), commit=True
    )
    row = (r2.pay_rows + r2.dues_rows)[0]
    assert row.is_hold is True and "dormant" in row.remarks.lower()


def test_migration_0005_sweeps_existing_closed_ev_debtors(db):
    small = make_person(db, "LegacySmall", balance=0, arrears=90000)
    make_ev(db, "EV-L1", provider="Raft", model="Regular")
    assign(db, small, "EV-L1", returned="2026-05-01", charged_through="2026-04-30")
    big = make_person(db, "LegacyBig", balance=0, arrears=400000)
    make_ev(db, "EV-L2", provider="Raft", model="Regular")
    assign(db, big, "EV-L2", returned="2026-05-01", charged_through="2026-04-30")
    # holder with debt but EV still open: must NOT be touched
    holder = make_person(db, "StillRiding", balance=0, arrears=300000)
    make_ev(db, "EV-L3", provider="Raft", model="Regular")
    assign(db, holder, "EV-L3", charged_through="2026-05-31")
    db.execute("DELETE FROM schema_migrations WHERE name='0005_deposit_for_closed_evs'")
    db.commit()
    from payout.db.migrations import run_migrations

    assert run_migrations(db, fresh_database=False) == ["0005_deposit_for_closed_evs"]
    db.commit()
    assert _out(db, small) == 0
    assert _out(db, big) == 400000 - CAP
    assert _out(db, holder) == 300000, "open-assignment riders keep their books untouched"


def test_story_flow_reports_deposit_applied(db):
    pid = make_person(db, "Story", balance=0, arrears=100000)
    db.commit()
    settle_from_deposit(db, pid, created_by="t")
    db.commit()
    c = _client(db)
    assert c.get("/api/dashboard/story").json()["flow"]["deposit_applied"] == 1000.0


def test_manual_arrears_write_off(db):
    """POST /persons/{id}/arrears/write-off: sponsored-EV debt zeroed with a
    reason, missed ledger days waived (not counted as collected), and the
    rent meter reset so billing starts on the given day."""
    wk = date(2026, 6, 1)
    pid = make_person(db, "Sponsored", balance=0, arrears=0)
    make_rider(db, pid, "SP1", "Blitz", "Sponsored")
    make_ev(db, "EV-SP", provider="Raft", model="Regular")
    assign(db, pid, "EV-SP", charged_through="2026-05-31")
    db.execute(
        "UPDATE person_registry SET deduction_company='Blitz', deduction_rider_id='SP1' "
        "WHERE person_id=?",
        (pid,),
    )
    db.commit()
    process_cycle("Blitz", wk, date(2026, 6, 7), _file([("X", 10)]), commit=True)
    assert _out(db, pid) == 125000

    c = _client(db)
    r = c.post(
        f"/api/persons/{pid}/arrears/write-off",
        json={
            "reason": "BlueDart-sponsored EV — rent not chargeable",
            "charge_rent_from": "2026-09-01",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["written_off"] == 1250.0  # rupees at the edge
    assert body["rent_charged_through"] == "2026-08-31"
    assert _out(db, pid) == 0
    # meter reset -> rent counts from 1 Sept
    m = db.execute(
        "SELECT rent_charged_through FROM ev_assignments WHERE person_id=? "
        "AND returned_date IS NULL",
        (pid,),
    ).fetchone()[0]
    assert m == "2026-08-31"
    # missed days waived, NOT recovered/collected
    statuses = {
        r2["billing_status"]
        for r2 in db.execute(
            "SELECT billing_status FROM ev_daily_ledger WHERE assigned_person_id=?", (pid,)
        )
    }
    assert "missed" not in statuses and "waived" in statuses
    # audited + surfaces in the corrections feed
    feed = c.get("/api/corrections").json()
    assert any(
        x["event_type"] == "RENT_REVERSAL" and "BlueDart-sponsored" in (x["remarks"] or "")
        for x in feed
    )
    # reason is mandatory
    assert c.post(f"/api/persons/{pid}/arrears/write-off", json={}).status_code == 400
