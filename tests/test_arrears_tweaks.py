"""Arrears tweaks (2026-09-02):

1. A credit balance is used to pay down EV arrears immediately (a rider who
   owed nothing on net used to show arrears forever if no payout cycle ever
   ran for them again) — at write time in the credit routes, and once for
   existing data via migration 0004.
2. A rider who RETURNED their EV but still owes back-rent goes dormant:
   hidden from the active Arrears view, debt kept silently, and any future
   payout for them is HELD with nothing auto-recovered.
"""

from __future__ import annotations

import io
from datetime import date

import pytest
from openpyxl import Workbook

from payout.domain.arrears import settle_arrears_from_credit
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


def _arrears(db, pid):
    return db.execute(
        "SELECT total_recovered, outstanding FROM ev_arrears WHERE person_id=?", (pid,)
    ).fetchone()


def _balance(db, pid):
    return db.execute("SELECT current_balance FROM balances WHERE person_id=?", (pid,)).fetchone()[
        0
    ]


# ── 1. credit vs arrears offset ──────────────────────────────────────────────


def test_settle_from_credit_full_overlap(db):
    pid = make_person(db, "Net-zero", balance=125000, arrears=125000)
    db.commit()
    assert settle_arrears_from_credit(db, pid, created_by="t") == 125000
    db.commit()
    assert _balance(db, pid) == 0
    rec, out = _arrears(db, pid)
    assert (rec, out) == (125000, 0)
    events = {
        r[0]: r[1]
        for r in db.execute("SELECT event_type, amount FROM transactions WHERE person_id=?", (pid,))
    }
    assert events["ADJUSTMENT"] == -125000, "the credit debit must be on the audit trail"
    assert events["RENT_RECOVERED"] == 125000


def test_settle_from_credit_partial_overlap(db):
    pid = make_person(db, "Partial", balance=50000, arrears=125000)
    db.commit()
    assert settle_arrears_from_credit(db, pid, created_by="t") == 50000
    assert _balance(db, pid) == 0
    assert _arrears(db, pid)["outstanding"] == 75000
    # nothing to do on a second call
    assert settle_arrears_from_credit(db, pid, created_by="t") == 0


def test_settle_noop_without_overlap(db):
    a = make_person(db, "OnlyCredit", balance=30000)
    b = make_person(db, "OnlyArrears", balance=-20000, arrears=40000)
    db.commit()
    assert settle_arrears_from_credit(db, a, created_by="t") == 0
    assert settle_arrears_from_credit(db, b, created_by="t") == 0
    assert _balance(db, a) == 30000
    assert _arrears(db, b)["outstanding"] == 40000


def test_migration_0004_sweeps_existing_overlaps(db):
    pid = make_person(db, "Legacy", balance=80000, arrears=80000)
    db.execute("DELETE FROM schema_migrations WHERE name='0004_offset_credit_vs_arrears'")
    db.commit()
    from payout.db.migrations import run_migrations

    assert run_migrations(db, fresh_database=False) == ["0004_offset_credit_vs_arrears"]
    db.commit()
    assert _balance(db, pid) == 0
    assert _arrears(db, pid)["outstanding"] == 0


def test_cod_clearance_credit_is_used_for_arrears(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    pid = make_person(db, "C", balance=0, arrears=40000)
    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("adm@t.test", hash_password("Admin-pass-1"), "admin"),
    )
    db.execute(
        "INSERT INTO cod_holds (cycle_start, cycle_end, company, rider_id, person_id, "
        "worker_code, amount, source) "
        "VALUES ('2026-06-01','2026-06-07','Myntra','C1',?,'C1',50000,'myntra_column')",
        (pid,),
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        assert (
            c.post(
                "/api/auth/login", data={"username": "adm@t.test", "password": "Admin-pass-1"}
            ).status_code
            == 200
        )
        r = c.post("/api/cod/clear", json={"person_id": pid, "ledger_amount": 500})
    assert r.status_code == 200, r.text
    assert r.json()["arrears_settled_from_credit"] == 400.0  # rupees at the edge
    assert r.json()["new_balance"] == 100.0  # ₹500 credit minus ₹400 arrears
    assert _arrears(db, pid)["outstanding"] == 0
    assert _balance(db, pid) == 10000


# ── 2. dormant arrears: hidden + future payouts held ─────────────────────────


def _dormant_rider(db, rid="D1", arrears=125000):
    """Returned their EV, still owes back-rent."""
    pid = make_person(db, "Dormant", balance=0, arrears=arrears)
    make_rider(db, pid, rid, "Blitz", "Dormant")
    make_ev(db, "EV-D", provider="Raft", model="Regular")
    assign(db, pid, "EV-D", returned="2026-05-20", charged_through="2026-05-19")
    db.commit()
    return pid


def test_future_payout_for_dormant_arrears_is_held_untouched(db):
    pid = _dormant_rider(db)
    r = process_cycle(
        "Blitz", date(2026, 6, 1), date(2026, 6, 7), _file([("D1", 3000)]), commit=True
    )
    rows = r.pay_rows + r.dues_rows
    assert len(rows) == 1
    row = rows[0]
    assert row.is_hold is True
    assert "dormant" in row.remarks.lower()
    assert row.arrears_recovered == 0
    assert row.new_arrears == 125000
    assert any("DORMANT" in w for w in r.warnings)
    # books: arrears untouched, no recovery written
    assert _arrears(db, pid)["outstanding"] == 125000
    assert (
        db.execute(
            "SELECT COUNT(*) FROM transactions WHERE person_id=? AND event_type='RENT_RECOVERED'",
            (pid,),
        ).fetchone()[0]
        == 0
    )


def test_force_release_overrides_the_dormant_hold(db):
    from payout.domain.engine import CycleOverrides, RiderOverride

    pid = _dormant_rider(db)
    ov = CycleOverrides(per_rider={"D1": RiderOverride(force_release=True)})
    r = process_cycle(
        "Blitz",
        date(2026, 6, 1),
        date(2026, 6, 7),
        _file([("D1", 3000)]),
        overrides=ov,
        commit=True,
    )
    row = (r.pay_rows + r.dues_rows)[0]
    assert row.is_hold is False
    # normal settlement applies again: arrears recovered from the payout
    assert row.arrears_recovered == 125000
    assert _arrears(db, pid)["outstanding"] == 0


def test_active_ev_holder_is_not_dormant(db):
    """Same arrears, but the EV is still held — normal recovery, no hold."""
    pid = make_person(db, "Active", balance=0, arrears=50000)
    make_rider(db, pid, "A1", "Blitz", "Active")
    make_ev(db, "EV-A", provider="Raft", model="Regular")
    assign(db, pid, "EV-A", charged_through="2026-05-31")
    db.commit()
    r = process_cycle(
        "Blitz", date(2026, 6, 1), date(2026, 6, 7), _file([("A1", 5000)]), commit=True
    )
    row = (r.pay_rows + r.dues_rows)[0]
    assert row.is_hold is False
    assert row.arrears_recovered == 50000
    assert _arrears(db, pid)["outstanding"] == 0


def test_arrears_view_hides_dormant_by_default(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    dormant = _dormant_rider(db)
    # active EV holder with arrears
    active = make_person(db, "Holder", balance=0, arrears=30000)
    make_ev(db, "EV-H", provider="Raft", model="Regular")
    assign(db, active, "EV-H", charged_through="2026-05-31")
    # general-dues-only rider (no EV ever): always listed
    dues_only = make_person(db, "DuesOnly", balance=-20000)
    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("adm@t.test", hash_password("Admin-pass-1"), "admin"),
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        c.post("/api/auth/login", data={"username": "adm@t.test", "password": "Admin-pass-1"})
        default = {r["person_id"]: r for r in c.get("/api/arrears").json()}
        both = {r["person_id"]: r for r in c.get("/api/arrears?include_dormant=true").json()}
    assert dormant not in default, "dormant rider must be hidden by default"
    assert active in default and dues_only in default
    assert dormant in both and bool(both[dormant]["dormant"]) is True
    assert bool(both[active]["dormant"]) is False


# ── 3. dormancy covers general dues too (no-open-EV = silent, any bucket) ────


def _dues_only_ex_ev_rider(db, rid="G1", dues=45000):
    """Returned their EV; zero EV arrears — the debt rolled into general
    carry-forward dues instead (the Dipanjan/Sayan shape)."""
    pid = make_person(db, "DuesDormant", balance=-dues)
    make_rider(db, pid, rid, "Blitz", "DuesDormant")
    make_ev(db, "EV-G", provider="Raft", model="Regular")
    assign(db, pid, "EV-G", returned="2026-07-10", charged_through="2026-07-09")
    db.commit()
    return pid


def test_dues_only_ex_ev_rider_is_dormant_in_arrears_view(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    pid = _dues_only_ex_ev_rider(db)
    # control: never-EV rider with dues stays on the active list
    bike = make_person(db, "BikeDues", balance=-30000)
    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("adm2@t.test", hash_password("Admin-pass-1"), "admin"),
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        c.post("/api/auth/login", data={"username": "adm2@t.test", "password": "Admin-pass-1"})
        default = {r["person_id"]: r for r in c.get("/api/arrears").json()}
        both = {r["person_id"]: r for r in c.get("/api/arrears?include_dormant=true").json()}
    assert pid not in default, "ex-EV rider with dues-only debt must be hidden by default"
    assert bike in default and bool(default[bike].get("dormant")) is False
    assert pid in both and bool(both[pid]["dormant"]) is True
    assert both[pid]["dues_outstanding"] == 450.0  # rupees at the edge


def test_future_payout_for_dues_only_ex_ev_rider_is_held(db):
    _dues_only_ex_ev_rider(db)
    r = process_cycle(
        "Blitz", date(2026, 8, 1), date(2026, 8, 7), _file([("G1", 2000)]), commit=True
    )
    row = (r.pay_rows + r.dues_rows)[0]
    assert row.is_hold is True
    assert "dormant" in row.remarks.lower()
    assert any("DORMANT" in w for w in r.warnings)


def test_bike_rider_with_dues_is_not_held(db):
    """Never held an EV — dues clear normally from the payout, no hold."""
    pid = make_person(db, "PureBike", balance=-20000)
    make_rider(db, pid, "B9", "Blitz", "PureBike")
    db.commit()
    r = process_cycle(
        "Blitz", date(2026, 8, 1), date(2026, 8, 7), _file([("B9", 1000)]), commit=True
    )
    row = (r.pay_rows + r.dues_rows)[0]
    assert row.is_hold is False
    assert _balance(db, pid) == 0  # ₹1000 payout cleared the ₹200 dues, rest released


def test_story_position_reports_dormant_dues_split(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    _dues_only_ex_ev_rider(db, rid="G2", dues=45000)  # dormant: dues bucket
    _dormant_rider(db, rid="D2", arrears=125000)  # dormant: EV-arrears bucket
    make_person(db, "BikeDues2", balance=-30000)  # active: never-EV
    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("adm3@t.test", hash_password("Admin-pass-1"), "admin"),
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        c.post("/api/auth/login", data={"username": "adm3@t.test", "password": "Admin-pass-1"})
        p = c.get("/api/dashboard/story").json()["position"]
    assert p["dues_dormant"] == 450.0  # rupees at the edge
    assert p["dues"] == 750.0  # dormant 450 + active bike 300
    assert p["ev_arrears_dormant"] == 1250.0
    assert p["dormant_riders"] == 2


def test_story_by_rider_flags_dormant_rows(db):
    """The Riders analytics tab must tag no-open-EV debtors as dormant so the
    UI can show them silently and keep them out of the chase total."""
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    dormant = _dormant_rider(db, rid="D3", arrears=125000)  # EV-arrears bucket
    dues_dormant = _dues_only_ex_ev_rider(db, rid="G3", dues=45000)  # dues bucket
    active = make_person(db, "Holder3", balance=0, arrears=30000)
    make_rider(db, active, "A3", "Blitz", "Holder3")
    make_ev(db, "EV-H3", provider="Raft", model="Regular")
    assign(db, active, "EV-H3", charged_through="2026-05-31")
    # put all three inside the window via a PAYOUT txn
    for pid in (dormant, dues_dormant, active):
        db.execute(
            "INSERT INTO transactions (person_id, company, cycle_start, cycle_end, "
            "event_type, amount, balance_after, created_at) "
            "VALUES (?, 'Blitz', '2026-08-01', '2026-08-07', 'PAYOUT', 100000, 0, "
            "'2026-08-03 10:00:00')",
            (pid,),
        )
    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("adm4@t.test", hash_password("Admin-pass-1"), "admin"),
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        c.post("/api/auth/login", data={"username": "adm4@t.test", "password": "Admin-pass-1"})
        rows = {
            r["person_id"]: r
            for r in c.get(
                "/api/dashboard/story/by?dim=rider&date_from=2026-08-01&date_to=2026-08-07"
            ).json()["rows"]
        }
    assert rows[dormant]["dormant"] is True
    assert rows[dues_dormant]["dormant"] is True
    assert rows[active]["dormant"] is False
