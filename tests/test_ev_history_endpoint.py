"""EV history must survive the /persons/{id} response.

Regression: get_person is annotated `-> PersonOut`, so FastAPI filtered the
response to PersonOut's fields. ev_history was merged on top of the model as
an extra dict key, so it was stripped — every rider showed zero EV history,
open or returned. Fixed by making ev_history a real PersonOut field.
"""

from __future__ import annotations

import pytest

from payout.api import ratelimit
from tests.conftest import assign, make_ev, make_person, make_rider


@pytest.fixture
def client(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api.app import app
    from payout.auth import hash_password

    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("adm@t.test", hash_password("Admin-pass-1"), "admin"),
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        c.post("/api/auth/login", data={"username": "adm@t.test", "password": "Admin-pass-1"})
        yield c


def test_history_present_while_open(client, db):
    pid = make_person(db, "Holder", balance=0)
    make_rider(db, pid, "H1", "Blitz", "Holder")
    make_ev(db, "EV-A", provider="Raft", model="Regular")
    assign(db, pid, "EV-A", handover="2026-08-01")
    db.commit()
    body = client.get(f"/api/persons/{pid}").json()
    assert len(body["ev_history"]) == 1
    h = body["ev_history"][0]
    assert h["ev_id"] == "EV-A"
    assert h["returned_date"] is None
    assert h["weekly_rate"] == 1250.0  # paise -> rupees at the edge


def test_history_survives_after_return(client, db):
    pid = make_person(db, "Returner", balance=0)
    make_rider(db, pid, "R1", "Blitz", "Returner")
    make_ev(db, "EV-B", provider="Raft", model="Regular")
    assign(db, pid, "EV-B", handover="2026-08-01")
    db.commit()
    r = client.post("/api/evs/return", json={"ev_id": "EV-B", "returned_date": "2026-08-20"})
    assert r.status_code == 200, r.text
    body = client.get(f"/api/persons/{pid}").json()
    assert body["ev"] is None  # no open EV now
    assert len(body["ev_history"]) == 1, "returned EV must still appear in history"
    assert body["ev_history"][0]["returned_date"] == "2026-08-20"


def test_two_evs_history_newest_first(client, db):
    pid = make_person(db, "Serial", balance=0)
    make_rider(db, pid, "S1", "Blitz", "Serial")
    make_ev(db, "EV-OLD", provider="Raft", model="Regular")
    make_ev(db, "EV-NEW", provider="Raft", model="Regular")
    assign(db, pid, "EV-OLD", handover="2026-06-01", returned="2026-07-01")
    assign(db, pid, "EV-NEW", handover="2026-07-05")
    db.commit()
    hist = client.get(f"/api/persons/{pid}").json()["ev_history"]
    assert [h["ev_id"] for h in hist] == ["EV-NEW", "EV-OLD"]  # open first, then newest
