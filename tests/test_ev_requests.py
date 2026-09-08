"""EV requests (2026-09-07): a recruiter asks the fleet desk for N vehicles.

Same shape as the money requests — recruiters ask and see only their own,
admins see everything and close each one — but the unit is EVs, not rupees,
and nothing touches the ledger.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from payout.api import ratelimit  # noqa: E402
from payout.api.app import app  # noqa: E402
from payout.auth import hash_password  # noqa: E402

_ADMIN = ("admin@t.test", "Admin-pass-1", "admin")
_REC = ("rec@t.test", "Recruit-pass-1", "recruiter")
_REC2 = ("rec2@t.test", "Recruit-pass-2", "recruiter")


@pytest.fixture
def client(db):
    for email, pw, role in (_ADMIN, _REC, _REC2):
        db.execute(
            "INSERT INTO users (email, password_hash, role, is_active, zone) VALUES (?,?,?,1,?)",
            (email, hash_password(pw), role, "South" if role == "recruiter" else None),
        )
    db.execute(
        "INSERT OR IGNORE INTO companies (company_name, parser_type, rider_id_column, "
        "payout_column) VALUES ('Kaptan', 'generic', 'rider_id', 'net_pay')"
    )
    db.execute(
        "INSERT INTO company_hubs (company, hub, zone, updated_by) VALUES (?,?,?,?)",
        ("Kaptan", "Belur", "North", "test"),
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _login(client, who):
    email, pw, _ = who
    r = client.post("/api/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_recruiter_asks_admin_fulfils(db, client):
    rec = _login(client, _REC)
    adm = _login(client, _ADMIN)
    r = client.post(
        "/api/ev-requests",
        json={"quantity": 3, "hub": "Belur", "company": "Kaptan", "note": "two joiners waiting"},
        headers=rec,
    )
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["quantity"] == 3 and req["status"] == "open"
    assert req["zone"] == "North"  # the store's zone wins over the recruiter's
    # the recruiter can't close their own ask
    assert client.post(f"/api/ev-requests/{req['id']}/fulfil", headers=rec).status_code == 403
    assert client.get("/api/ev-requests/summary", headers=adm).json() == {"open": 1, "units": 3}
    # fulfil for fewer units than asked
    r = client.post(
        f"/api/ev-requests/{req['id']}/fulfil",
        json={"quantity": 2, "note": "two spare at Belur"},
        headers=adm,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "fulfilled" and r.json()["fulfilled_quantity"] == 2
    assert r.json()["resolution_note"] == "two spare at Belur"
    # closing twice is a conflict, and the queue is empty again
    assert client.post(f"/api/ev-requests/{req['id']}/reject", headers=adm).status_code == 409
    assert client.get("/api/ev-requests/summary", headers=adm).json() == {"open": 0, "units": 0}
    act = db.execute(
        "SELECT action, entity_type FROM activity_log ORDER BY id DESC LIMIT 2"
    ).fetchall()
    assert {a["action"] for a in act} == {"ev_request.create", "ev_request.fulfil"}
    assert {a["entity_type"] for a in act} == {"ev_request"}


def test_zone_falls_back_to_the_recruiter_and_reject_keeps_the_note(db, client):
    rec = _login(client, _REC)
    adm = _login(client, _ADMIN)
    r = client.post("/api/ev-requests", json={"quantity": 1}, headers=rec)
    assert r.status_code == 201 and r.json()["zone"] == "South"
    rid = r.json()["id"]
    r = client.post(f"/api/ev-requests/{rid}/reject", json={"note": "none free"}, headers=adm)
    assert r.status_code == 200
    assert r.json()["status"] == "rejected" and r.json()["resolution_note"] == "none free"
    assert r.json()["fulfilled_quantity"] is None


def test_recruiters_see_only_their_own_and_can_withdraw(db, client):
    rec, rec2 = _login(client, _REC), _login(client, _REC2)
    adm = _login(client, _ADMIN)
    mine = client.post("/api/ev-requests", json={"quantity": 2}, headers=rec).json()
    theirs = client.post("/api/ev-requests", json={"quantity": 5}, headers=rec2).json()
    assert [r["id"] for r in client.get("/api/ev-requests", headers=rec).json()] == [mine["id"]]
    assert len(client.get("/api/ev-requests", headers=adm).json()) == 2
    assert client.get("/api/ev-requests/summary", headers=rec).json() == {"open": 1, "units": 2}
    # can't withdraw someone else's
    assert client.post(f"/api/ev-requests/{theirs['id']}/cancel", headers=rec).status_code == 403
    r = client.post(f"/api/ev-requests/{mine['id']}/cancel", headers=rec)
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert client.get("/api/ev-requests?status=open", headers=adm).json()[0]["id"] == theirs["id"]


def test_filters_and_validation(db, client):
    rec = _login(client, _REC)
    adm = _login(client, _ADMIN)
    client.post("/api/ev-requests", json={"quantity": 2, "hub": "Belur"}, headers=rec)
    client.post("/api/ev-requests", json={"quantity": 1}, headers=rec)
    assert len(client.get("/api/ev-requests?zone=North", headers=adm).json()) == 1
    assert len(client.get("/api/ev-requests?zone=south", headers=adm).json()) == 1
    assert client.get("/api/ev-requests?zone=West", headers=adm).status_code == 400
    assert client.post("/api/ev-requests", json={"quantity": 0}, headers=rec).status_code == 422
    assert client.post("/api/ev-requests", json={"quantity": 99}, headers=rec).status_code == 422
    r = client.post("/api/ev-requests", json={"quantity": 1, "company": "Nope"}, headers=rec)
    assert r.status_code == 404
    # counts stay counts — 2 EVs must not come back rupeeized as 0.02
    assert client.get("/api/ev-requests", headers=rec).json()[0]["quantity"] in (1, 2)
