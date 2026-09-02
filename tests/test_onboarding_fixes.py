"""Onboarding fixes (2026-09-02):

1. A new rider with the SAME NAME as an existing person must get a NEW
   person — never a silent merge (two different Amit Naskars are two people).
   Linking is explicit: pass person_id / use the onboarding "link" action.
2. Myntra payout files call the name column "Worker Name" — the parser must
   pick it up for the onboarding panel.
3. EVs can be assigned by person_id directly, not only (rider_id, company).
"""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from tests.conftest import make_ev, make_person, make_rider


@pytest.fixture
def client(db):
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
    with TestClient(app) as c:
        assert (
            c.post(
                "/api/auth/login", data={"username": "adm@t.test", "password": "Admin-pass-1"}
            ).status_code
            == 200
        )
        yield c


# ── 1. no name-only auto-link ────────────────────────────────────────────────


def test_same_name_creates_a_new_person(db, client):
    existing = make_person(db, "Amit Naskar")
    make_rider(db, existing, "J1", "Jiffy", "Amit Naskar")
    db.commit()
    r = client.post(
        "/api/riders/onboard-unknowns",
        json={
            "company": "Blitz",
            "rows": [{"rider_id": "B9", "action": "create", "name": "Amit Naskar"}],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["committed"] and body["summary"]["created"] == 1
    new_pid = body["created"][0]["person_id"]
    assert new_pid != existing, "same name must NOT merge into the existing person"
    # Two distinct persons with the same display name now exist.
    n = db.execute(
        "SELECT COUNT(*) FROM person_registry WHERE display_name='Amit Naskar'"
    ).fetchone()[0]
    assert n == 2


def test_explicit_link_still_works(db, client):
    existing = make_person(db, "Same Guy")
    make_rider(db, existing, "J2", "Jiffy", "Same Guy")
    db.commit()
    r = client.post(
        "/api/riders/onboard-unknowns",
        json={
            "company": "Blitz",
            "rows": [{"rider_id": "B10", "action": "link", "link_to_person_id": existing}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["linked"] == [{"rider_id": "B10", "person_id": existing}]


def test_shared_account_is_still_a_conflict(db, client):
    existing = make_person(db, "Owner")
    make_rider(db, existing, "J3", "Jiffy", "Owner")
    db.execute("UPDATE rider_master SET account_no='111222333' WHERE rider_id='J3'")
    db.commit()
    r = client.post(
        "/api/riders/onboard-unknowns",
        json={
            "company": "Blitz",
            "rows": [
                {
                    "rider_id": "B11",
                    "action": "create",
                    "name": "Somebody Else",
                    "account_no": "111222333",
                }
            ],
        },
    )
    body = r.json()
    assert body["committed"] is False and body["summary"]["errors"] == 1


# ── 2. Myntra "Worker Name" header ───────────────────────────────────────────


def test_parser_reads_worker_name_column(db):
    from payout.domain.engine import process_cycle

    wb = Workbook()
    ws = wb.active
    ws.append(["rider_id", "Worker Name", "net_pay"])
    ws.append(["NEW1", "Fresh Rider", 1000])
    buf = io.BytesIO()
    wb.save(buf)
    r = process_cycle("Blitz", "2026-06-01", "2026-06-07", buf.getvalue(), commit=False)
    unk = [u for u in r.unknown_riders if u["rider_id"] == "NEW1"]
    assert unk and unk[0].get("name") == "Fresh Rider", (
        "'Worker Name' header must feed the onboarding panel's name"
    )


# ── 3. assign EV by person_id ────────────────────────────────────────────────


def test_assign_ev_by_person_id(db, client):
    pid = make_person(db, "Direct Assign")
    make_ev(db, "EV-P1", provider="Raft", model="Regular")
    db.commit()
    r = client.post("/api/evs/assign", json={"ev_id": "EV-P1", "person_id": pid})
    assert r.status_code == 200, r.text
    assert r.json()["person_id"] == pid
    open_a = db.execute(
        "SELECT person_id FROM ev_assignments WHERE ev_id='EV-P1' AND returned_date IS NULL"
    ).fetchone()
    assert open_a["person_id"] == pid
    # Unknown person -> 404; neither selector -> 400.
    make_ev(db, "EV-P2", provider="Raft", model="Regular")
    db.commit()
    assert (
        client.post("/api/evs/assign", json={"ev_id": "EV-P2", "person_id": 999999}).status_code
        == 404
    )
    assert client.post("/api/evs/assign", json={"ev_id": "EV-P2"}).status_code == 400
