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
    off nothing (return date after the cycle); the admin's close-out (deposit
    held) clears the debt from the deposit and the leftover goes to the
    rider's next payout, so the rider is NOT dormant."""
    wk = date(2026, 6, 1)
    pid = make_person(db, "SmallDebt", balance=0, arrears=0)
    make_rider(db, pid, "D1", "Kaptan", "SmallDebt")
    make_ev(db, "EV-D1", provider="Raft", model="Regular")
    assign(db, pid, "EV-D1", charged_through="2026-05-31")
    db.execute(
        "UPDATE person_registry SET deduction_company='Kaptan', deduction_rider_id='D1' "
        "WHERE person_id=?",
        (pid,),
    )
    db.commit()
    process_cycle("Kaptan", wk, date(2026, 6, 7), _file([("X", 10)]), commit=True)
    assert _out(db, pid) == 125000

    c = _client(db)
    r = c.post("/api/evs/return", json={"ev_id": "EV-D1", "returned_date": "2026-06-08"})
    assert r.status_code == 200, r.text
    # Nothing settled yet: the web now asks what happened to the deposit.
    assert "deposit_applied" not in r.json()["heal"]
    prompt = r.json()["closeout"]
    assert prompt["ev_id"] == "EV-D1" and prompt["suggested"]["rent_charges"] == 1250.0
    assert prompt["suggested"]["sd_amount"] == 2700.0
    assert _out(db, pid) == 125000
    pending = c.get("/api/evs/closeouts").json()
    assert [p["assignment_id"] for p in pending] == [prompt["assignment_id"]]

    r = c.post(
        f"/api/evs/closeouts/{prompt['assignment_id']}",
        json={"sd_returned": False, "damage_charges": 0, "credit_next_payout": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rent_applied"] == 1250.0 and body["refund_due"] == 1450.0
    assert body["refund_mode"] == "next_payout" and body["shortfall"] == 0
    assert _out(db, pid) == 0
    assert c.get("/api/evs/closeouts").json() == []
    # Closing out twice is refused.
    assert c.post(f"/api/evs/closeouts/{prompt['assignment_id']}", json={}).status_code == 400
    # Not dormant any more, and the ₹1,450 leftover rides out with the next payout.
    r2 = process_cycle(
        "Kaptan", date(2026, 6, 8), date(2026, 6, 14), _file([("D1", 2000)]), commit=True
    )
    row = (r2.pay_rows + r2.dues_rows)[0]
    assert row.is_hold is False
    assert row.prev_balance == 145000 and row.released == 200000 + 145000


def test_return_with_big_debt_keeps_surplus_dormant(db):
    """Two absent weeks + prior arrears (₹5,250 total > cap): the close-out
    (deposit held, nothing else) knocks ₹2,700 off, the surplus stays owed
    and the rider stays dormant-held."""
    wk = date(2026, 6, 1)
    pid = make_person(db, "BigDebt", balance=0, arrears=275000)
    make_rider(db, pid, "D2", "Kaptan", "BigDebt")
    make_ev(db, "EV-D2", provider="Raft", model="Regular")
    assign(db, pid, "EV-D2", charged_through="2026-05-31")
    db.execute(
        "UPDATE person_registry SET deduction_company='Kaptan', deduction_rider_id='D2' "
        "WHERE person_id=?",
        (pid,),
    )
    db.commit()
    process_cycle("Kaptan", wk, date(2026, 6, 7), _file([("X", 10)]), commit=True)
    assert _out(db, pid) == 275000 + 125000

    c = _client(db)
    r = c.post("/api/evs/return", json={"ev_id": "EV-D2", "returned_date": "2026-06-08"})
    assert r.status_code == 200, r.text
    aid = r.json()["closeout"]["assignment_id"]
    r = c.post(f"/api/evs/closeouts/{aid}", json={"sd_returned": False})
    assert r.status_code == 200, r.text
    assert r.json()["rent_applied"] == 2700.0 and r.json()["refund_due"] == 0
    assert _out(db, pid) == 275000 + 125000 - CAP
    # Still dormant: future payout held untouched.
    r2 = process_cycle(
        "Kaptan", date(2026, 6, 8), date(2026, 6, 14), _file([("D2", 2000)]), commit=True
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
    make_rider(db, pid, "SP1", "Kaptan", "Sponsored")
    make_ev(db, "EV-SP", provider="Raft", model="Regular")
    assign(db, pid, "EV-SP", charged_through="2026-05-31")
    db.execute(
        "UPDATE person_registry SET deduction_company='Kaptan', deduction_rider_id='SP1' "
        "WHERE person_id=?",
        (pid,),
    )
    db.commit()
    process_cycle("Kaptan", wk, date(2026, 6, 7), _file([("X", 10)]), commit=True)
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


def test_closeout_variants(db):
    """Deposit returned in cash (damage becomes dues); deposit held with damage
    beyond it (excess becomes dues); deposit held, leftover refunded in cash."""
    c = _client(db)

    def closed(tag, arrears=0):
        pid = make_person(db, tag, balance=0, arrears=arrears)
        make_rider(db, pid, tag, "Kaptan", tag)
        make_ev(db, "EV-" + tag, provider="Raft", model="Regular")
        aid = assign(db, pid, "EV-" + tag, handover="2026-06-01", charged_through="2026-06-07")
        db.commit()
        r = c.post("/api/evs/to-spare", json={"ev_id": "EV-" + tag, "returned_date": "2026-06-08"})
        assert r.status_code == 200, r.text
        assert r.json()["closeout"]["assignment_id"] == aid
        return pid, aid

    def balance(pid):
        row = db.execute(
            "SELECT current_balance FROM balances WHERE person_id=?", (pid,)
        ).fetchone()
        return int(row["current_balance"]) if row else 0

    # 1) SD given back in cash, ₹400 of damage → the rider owes ₹400.
    pid, aid = closed("Cash")
    r = c.post(f"/api/evs/closeouts/{aid}", json={"sd_returned": True, "damage_charges": 400})
    assert r.status_code == 200, r.text
    assert r.json()["sd_amount"] == 0 and r.json()["shortfall"] == 400.0
    assert balance(pid) == -40000

    # 2) SD held, ₹1,000 rent owed, ₹2,000 damage → ₹300 beyond the deposit becomes dues.
    pid, aid = closed("Big", arrears=100000)
    r = c.post(f"/api/evs/closeouts/{aid}", json={"sd_returned": False, "damage_charges": 2000})
    body = r.json()
    assert body["rent_applied"] == 1000.0 and body["refund_due"] == 0 and body["shortfall"] == 300.0
    assert _out(db, pid) == 0 and balance(pid) == -30000

    # 3) SD held, nothing owed, refunded in cash → recorded, no book movement.
    pid, aid = closed("Clean")
    r = c.post(
        f"/api/evs/closeouts/{aid}",
        json={"sd_returned": False, "credit_next_payout": False, "note": "Paid at the hub"},
    )
    body = r.json()
    assert body["refund_due"] == 2700.0 and body["refund_mode"] == "cash"
    assert balance(pid) == 0
    hist = c.get("/api/evs/closeouts?pending=false&ev_id=EV-Clean").json()
    assert len(hist) == 1 and hist[0]["note"] == "Paid at the hub" and hist[0]["name"] == "Clean"
    # The admin can override the rent figure; the deposit still only clears real debt.
    pid, aid = closed("Over", arrears=50000)
    body = c.post(f"/api/evs/closeouts/{aid}", json={"rent_charges": 5000}).json()
    assert body["rent_charges"] == 5000.0 and body["rent_applied"] == 500.0
    assert body["refund_due"] == 2200.0 and body["refund_mode"] == "next_payout"
    assert balance(pid) == 220000
