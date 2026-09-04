"""Suspected-returns radar + corrections feed."""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from openpyxl import Workbook

from payout.domain.engine import process_cycle
from tests.conftest import assign, make_ev, make_person, make_rider


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


def _seed_holder(db, rid, ev_id):
    pid = make_person(db, f"P-{rid}", balance=0, arrears=0)
    make_rider(db, pid, rid, "Blitz", f"P-{rid}")
    make_ev(db, ev_id, provider="Raft", model="Regular")
    wk0 = date(2026, 6, 1)
    assign(db, pid, ev_id, charged_through=(wk0 - timedelta(days=1)).isoformat())
    db.execute(
        "UPDATE person_registry SET deduction_company='Blitz', deduction_rider_id=? "
        "WHERE person_id=?",
        (rid, pid),
    )
    db.commit()
    return pid


def _run_weeks(absent_rid, present_rid, n=2):
    wk0 = date(2026, 6, 1)
    for i in range(n):
        s = wk0 + timedelta(weeks=i)
        r = process_cycle(
            "Blitz", s, s + timedelta(days=6), _file([(present_rid, 4000)]), commit=True
        )
    return r


def test_radar_flags_two_missed_cycles_and_engine_warns(db):
    _seed_holder(db, "S1", "EV-S1")  # will vanish
    _seed_holder(db, "S2", "EV-S2")  # keeps working
    r = _run_weeks("S1", "S2", n=2)
    # Engine warned on the SECOND consecutive miss, before commit.
    assert any("SUSPECTED RETURN" in w and "S1" in w for w in r.warnings)
    assert not any("S2" in w for w in r.warnings if "SUSPECTED" in w)

    c = _client(db)
    body = c.get("/api/evs/suspected-returns").json()
    assert [x["ev_id"] for x in body] == ["EV-S1"]
    row = body[0]
    assert row["missed_cycles"] == 2
    assert row["missed_since"] == "2026-06-01"
    assert row["suggested_return_date"] == "2026-06-01"
    assert row["missed_amount"] == 2500.0  # rupees at the edge
    # One cycle missed only -> not flagged at min_cycles=2, visible at 1.
    assert c.get("/api/evs/suspected-returns?min_cycles=3").json() == []


def test_radar_clears_after_backdated_return(db):
    pid = _seed_holder(db, "S3", "EV-S3")
    _seed_holder(db, "S4", "EV-S4")
    _run_weeks("S3", "S4", n=2)
    c = _client(db)
    assert len(c.get("/api/evs/suspected-returns").json()) == 1
    r = c.post("/api/evs/return", json={"ev_id": "EV-S3", "returned_date": "2026-06-01"})
    assert r.status_code == 200, r.text
    assert r.json()["heal"]["arrears_written_off"] == 2500.0
    assert c.get("/api/evs/suspected-returns").json() == []
    out = db.execute("SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()[0]
    assert out == 0


def test_corrections_feed_shows_manual_rows_only(db):
    pid = _seed_holder(db, "S5", "EV-S5")
    _run_weeks("S5", "S5", n=1)  # normal cycle: engine rows, none manual
    c = _client(db)
    assert c.get("/api/corrections").json() == []
    # A manual balance adjustment appears; the cycle's PAYOUT/RENT rows don't.
    r = c.post(
        "/api/ledger/adjustments",
        json={"person_id": pid, "amount": 150, "reason": "cash received"},
    )
    assert r.status_code == 200, r.text
    feed = c.get("/api/corrections").json()
    assert len(feed) == 1
    row = feed[0]
    assert row["event_type"] == "ADJUSTMENT"
    assert row["amount"] == 150.0
    assert row["created_by"] == "adm@t.test"
    assert row["display_name"] == "P-S5"
    # And a heal's reversal rows land in the feed too.
    r = c.post("/api/evs/amend-return", json={"ev_id": "EV-S5", "returned_date": "2026-06-04"})
    assert r.status_code in (200, 404)  # 404 if no return recorded yet
    r = c.post("/api/evs/return", json={"ev_id": "EV-S5", "returned_date": "2026-06-04"})
    assert r.status_code == 200
    feed = c.get("/api/corrections").json()
    assert any(x["event_type"] == "ADJUSTMENT" and "EV-S5" in (x["remarks"] or "") for x in feed)
    # person filter
    assert all(x["person_id"] == pid for x in c.get(f"/api/corrections?person_id={pid}").json())


def test_dismiss_not_a_return_hides_row_and_reflags_after_four_more_cycles(db):
    """'They still have it': an 'absent' dismissal hides the row, keeps the
    rent accruing, and resurfaces after 4 more missed cycles; a 'sponsored'
    dismissal is permanent; undismiss brings it straight back."""
    pid = _seed_holder(db, "S6", "EV-S6")
    _seed_holder(db, "S7", "EV-S7")
    _run_weeks("S6", "S7", n=2)
    c = _client(db)
    assert [x["ev_id"] for x in c.get("/api/evs/suspected-returns").json()] == ["EV-S6"]

    r = c.post(
        "/api/evs/suspected-returns/dismiss",
        json={"ev_id": "EV-S6", "kind": "absent", "reason": "on leave, called him"},
    )
    assert r.status_code == 200, r.text
    assert c.get("/api/evs/suspected-returns").json() == []
    shown = c.get("/api/evs/suspected-returns?include_dismissed=1").json()
    assert shown[0]["dismissed"]["kind"] == "absent"
    assert shown[0]["dismissed"]["missed_cycles_then"] == 2
    assert shown[0]["dismissed"]["reflagged"] is False
    # Rent keeps accruing to arrears exactly as before.
    out = db.execute("SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()[0]
    assert out == 250000

    # Three more silent weeks: still hidden. The fourth: back on the list.
    wk = date(2026, 6, 15)
    for i in range(3):
        s = wk + timedelta(weeks=i)
        process_cycle("Blitz", s, s + timedelta(days=6), _file([("S7", 4000)]), commit=True)
    assert c.get("/api/evs/suspected-returns").json() == []
    s = wk + timedelta(weeks=3)
    process_cycle("Blitz", s, s + timedelta(days=6), _file([("S7", 4000)]), commit=True)
    back = c.get("/api/evs/suspected-returns").json()
    assert [x["ev_id"] for x in back] == ["EV-S6"]
    assert back[0]["dismissed"]["reflagged"] is True and back[0]["missed_cycles"] == 6

    # Sponsored: gone for good, whatever the streak does.
    r = c.post(
        "/api/evs/suspected-returns/dismiss",
        json={"ev_id": "EV-S6", "kind": "sponsored", "reason": "BlueDart pays the rent"},
    )
    assert r.status_code == 200
    s = wk + timedelta(weeks=4)
    process_cycle("Blitz", s, s + timedelta(days=6), _file([("S7", 4000)]), commit=True)
    assert c.get("/api/evs/suspected-returns").json() == []
    # Undismiss → straight back.
    assert (
        c.post("/api/evs/suspected-returns/undismiss", json={"ev_id": "EV-S6"}).status_code == 200
    )
    assert [x["ev_id"] for x in c.get("/api/evs/suspected-returns").json()] == ["EV-S6"]
    # Validation.
    assert (
        c.post(
            "/api/evs/suspected-returns/dismiss",
            json={"ev_id": "EV-S6", "kind": "x", "reason": "r"},
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/evs/suspected-returns/dismiss", json={"ev_id": "EV-S6", "kind": "absent"}
        ).status_code
        == 400
    )
    assert (
        c.post(
            "/api/evs/suspected-returns/dismiss",
            json={"ev_id": "NOPE", "kind": "absent", "reason": "r"},
        ).status_code
        == 404
    )
