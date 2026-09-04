"""Four small operator asks (2026-09-03):

1. Adding an EV can hand it to a rider by Person ID in the same request.
2. A person carrying a system placeholder id (QSPEND…) loses it the moment a
   real company id is tagged to them — history follows the real id.
3. A RETURNED EV can be brought back into the spare pool (and a spare can be
   returned) — the two idle states flip freely.
4. Nobody below creator learns the creator tier exists: creators list as
   admins, creator endpoints refuse with a generic message, the API docs are
   creator-only.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from payout.api import ratelimit  # noqa: E402
from payout.api.app import app  # noqa: E402
from payout.auth import hash_password  # noqa: E402
from tests.conftest import assign, make_ev, make_person, make_rider  # noqa: E402

_CREATOR = ("owner@t.test", "Owner-pass-1", "creator")
_ADMIN = ("admin@t.test", "Admin-pass-1", "admin")
_USER = ("user@t.test", "User-pass-1", "user")


@pytest.fixture
def client(db):
    for email, pw, role in (_CREATOR, _ADMIN, _USER):
        db.execute(
            "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
            (email, hash_password(pw), role),
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


# ── 1. add EV + assign by person id ──────────────────────────────────────────


def test_add_ev_assigns_to_person_in_one_call(db, client):
    pid = make_person(db, "Sona Dutta")
    db.commit()
    h = _login(client, _ADMIN)
    r = client.post(
        "/api/evs",
        json={
            "ev_id": "RAFT-NEW-1",
            "provider": "Blive",
            "model": "Standard",
            "person_id": pid,
            "handover_date": "2026-09-01",
        },
        headers=h,
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "in_use"
    assert body["current_person_id"] == pid
    assert body["handover_date"] == "2026-09-01"
    a = db.execute(
        "SELECT person_id, handover_date FROM ev_assignments "
        "WHERE ev_id='RAFT-NEW-1' AND returned_date IS NULL"
    ).fetchone()
    assert tuple(a) == (pid, "2026-09-01")
    assert (
        db.execute("SELECT status FROM ev_units WHERE ev_id='RAFT-NEW-1'").fetchone()[0] == "in_use"
    )


def test_add_ev_with_unknown_person_creates_nothing(db, client):
    h = _login(client, _ADMIN)
    r = client.post(
        "/api/evs",
        json={"ev_id": "RAFT-NEW-2", "provider": "Blive", "model": "Standard", "person_id": 9999},
        headers=h,
    )
    assert r.status_code == 404
    assert db.execute("SELECT 1 FROM ev_units WHERE ev_id='RAFT-NEW-2'").fetchone() is None


def test_add_ev_refuses_person_who_already_holds_an_ev(db, client):
    pid = make_person(db, "Busy Rider")
    make_ev(db, "EV-HELD")
    assign(db, pid, "EV-HELD", handover="2026-08-01")
    db.commit()
    h = _login(client, _ADMIN)
    r = client.post(
        "/api/evs",
        json={"ev_id": "RAFT-NEW-3", "provider": "Blive", "model": "Standard", "person_id": pid},
        headers=h,
    )
    assert r.status_code == 409
    assert db.execute("SELECT 1 FROM ev_units WHERE ev_id='RAFT-NEW-3'").fetchone() is None


# ── 2. placeholder retired when a real id is tagged ──────────────────────────


def _placeholder_rows(db, pid):
    return [
        r[0]
        for r in db.execute(
            "SELECT rider_id FROM rider_master WHERE person_id=? AND rider_id LIKE 'QSPEND%'",
            (pid,),
        )
    ]


def test_onboarding_link_retires_the_placeholder(db, client):
    h = _login(client, _ADMIN)
    # Rider created before Spencer's issued an id → placeholder.
    r = client.post("/api/riders", json={"company": "Spencer's", "name": "New Joiner"}, headers=h)
    assert r.status_code == 201, r.text
    ph = r.json()["rider_id"]
    pid = r.json()["person_id"]
    assert ph.startswith("QSPEND")
    # Some history already sits on the placeholder.
    db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after) VALUES (?, ?, 'Spencer''s', '2026-08-03', "
        "'2026-08-09', 'OPENING', 0, 0)",
        (pid, ph),
    )
    db.commit()

    # The id turns up in a payout file → operator links it to the person.
    r = client.post(
        "/api/riders/onboard-unknowns",
        json={
            "company": "Spencer's",
            "rows": [{"rider_id": "9876543210", "action": "link", "link_to_person_id": pid}],
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["committed"] is True

    assert _placeholder_rows(db, pid) == []
    ids = [r[0] for r in db.execute("SELECT rider_id FROM rider_master WHERE person_id=?", (pid,))]
    assert ids == ["9876543210"]
    assert (
        db.execute("SELECT rider_id FROM transactions WHERE person_id=?", (pid,)).fetchone()[0]
        == "9876543210"
    )
    anchor = db.execute(
        "SELECT deduction_rider_id FROM person_registry WHERE person_id=?", (pid,)
    ).fetchone()[0]
    assert anchor == "9876543210"


def test_placeholder_survives_when_real_id_is_at_another_company(db, client):
    """A Spencer's placeholder stays while the person only has a real id at
    Blitz — the placeholder is per company."""
    h = _login(client, _ADMIN)
    r = client.post("/api/riders", json={"company": "Spencer's", "name": "Two Co"}, headers=h)
    pid = r.json()["person_id"]
    r = client.post(
        "/api/riders",
        json={"company": "Blitz", "name": "Two Co", "rider_id": "B77", "person_id": pid},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert len(_placeholder_rows(db, pid)) == 1


def test_link_riders_merge_retires_placeholder(db, client):
    pid_ph = make_person(db, "Placeholder Person")
    make_rider(db, pid_ph, "QSPEND0007", "Spencer's", "Placeholder Person")
    pid_real = make_person(db, "Real Person")
    make_rider(db, pid_real, "9998887776", "Spencer's", "Real Person")
    db.commit()
    h = _login(client, _ADMIN)
    r = client.post(
        "/api/persons/link",
        json={"primary_person_id": pid_real, "secondary_person_id": pid_ph},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["placeholders_retired"] == ["QSPEND0007"]
    ids = [
        r[0] for r in db.execute("SELECT rider_id FROM rider_master WHERE person_id=?", (pid_real,))
    ]
    assert ids == ["9998887776"]


# ── 3. returned ↔ spare ──────────────────────────────────────────────────────


def test_returned_ev_can_come_back_as_spare_and_go_again(db, client):
    make_ev(db, "EV-IDLE", status="returned")
    db.commit()
    h = _login(client, _ADMIN)
    r = client.post("/api/evs/to-spare", json={"ev_id": "EV-IDLE"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["spare"] is True and r.json()["previous_status"] == "returned"
    assert db.execute("SELECT status FROM ev_units WHERE ev_id='EV-IDLE'").fetchone()[0] == "spare"
    # already spare → nothing to do
    r = client.post("/api/evs/to-spare", json={"ev_id": "EV-IDLE"}, headers=h)
    assert r.status_code == 409
    # and back out to the provider
    r = client.post("/api/evs/return", json={"ev_id": "EV-IDLE"}, headers=h)
    assert r.status_code == 200, r.text
    assert (
        db.execute("SELECT status FROM ev_units WHERE ev_id='EV-IDLE'").fetchone()[0] == "returned"
    )


def test_to_spare_unknown_ev_is_404(db, client):
    h = _login(client, _ADMIN)
    r = client.post("/api/evs/to-spare", json={"ev_id": "NOPE"}, headers=h)
    assert r.status_code == 404


# ── 4. the creator tier is invisible below creator ───────────────────────────


def test_admins_and_users_see_creators_as_admins(client):
    for who in (_ADMIN, _USER):
        h = _login(client, who)
        rows = client.get("/api/users", headers=h).json()
        roles = {r["email"]: r["role"] for r in rows}
        assert roles[_CREATOR[0]] == "admin"
        assert "creator" not in roles.values()
    h = _login(client, _CREATOR)
    rows = client.get("/api/users", headers=h).json()
    assert {r["email"]: r["role"] for r in rows}[_CREATOR[0]] == "creator"


def test_creator_endpoints_refuse_generically(client):
    h = _login(client, _ADMIN)
    r = client.get("/api/creator/system/stats", headers=h)
    assert r.status_code == 403
    assert "creator" not in r.text.lower()
    r = client.patch("/api/users/user@t.test/role", json={"role": "admin"}, headers=h)
    assert r.status_code == 403 and "creator" not in r.text.lower()


def test_api_docs_are_creator_only(client):
    assert client.get("/docs").status_code == 401
    assert client.get("/openapi.json").status_code == 401
    h = _login(client, _ADMIN)
    assert client.get("/docs", headers=h).status_code == 403
    assert client.get("/openapi.json", headers=h).status_code == 403
    h = _login(client, _CREATOR)
    assert client.get("/docs", headers=h).status_code == 200
    r = client.get("/openapi.json", headers=h)
    assert r.status_code == 200 and "/api/creator/system/stats" in r.json()["paths"]


# ── 5. creator sets a user's password; admins cannot ─────────────────────────


def test_creator_sets_password_and_user_signs_in_with_it(client):
    h = _login(client, _CREATOR)
    r = client.patch(
        "/api/users/user@t.test/password", json={"new_password": "Fresh-pass-9"}, headers=h
    )
    assert r.status_code == 200, r.text
    assert r.json()["password_set"] is True
    # Old password dead, new one works.
    assert (
        client.post(
            "/api/auth/login", data={"username": "user@t.test", "password": _USER[1]}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/auth/login", data={"username": "user@t.test", "password": "Fresh-pass-9"}
        ).status_code
        == 200
    )
    # Too short, unknown user, and non-creators are refused.
    assert (
        client.patch(
            "/api/users/user@t.test/password", json={"new_password": "short"}, headers=h
        ).status_code
        == 400
    )
    assert (
        client.patch(
            "/api/users/nobody@t.test/password", json={"new_password": "Fresh-pass-9"}, headers=h
        ).status_code
        == 404
    )
    ha = _login(client, _ADMIN)
    assert (
        client.patch(
            "/api/users/user@t.test/password", json={"new_password": "Fresh-pass-9"}, headers=ha
        ).status_code
        == 403
    )


def test_manage_set_password_cli(db, monkeypatch):
    import payout.cli.manage as manage

    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,0)",
        ("locked@t.test", hash_password("Old-pass-11"), "admin"),
    )
    db.commit()
    monkeypatch.setattr("payout.db.connection.get_connection", lambda: db, raising=True)
    db.close = lambda: None  # the command closes what it opens; keep the fixture alive

    class A:
        email = "locked@t.test"
        password = "New-pass-22"

    manage.cmd_set_password(A())
    row = db.execute(
        "SELECT password_hash, is_active FROM users WHERE email='locked@t.test'"
    ).fetchone()
    from payout.auth import verify_password

    assert verify_password("New-pass-22", row["password_hash"]) and row["is_active"] == 1


# ── 6. phone number as a second login id ─────────────────────────────────────


def test_phone_login_and_management(client):
    h = _login(client, _CREATOR)
    # Creator sets a phone in any common spelling; it is stored as E.164.
    r = client.patch("/api/users/user@t.test/phone", json={"phone": "98765 43210"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == "+919876543210"
    # Login with the phone (three spellings) and the password works; wrong password does not.
    for ident in ("9876543210", "+91 98765-43210", "09876543210"):
        r = client.post("/api/auth/login", data={"username": ident, "password": _USER[1]})
        assert r.status_code == 200, (ident, r.text)
        assert r.json()["email"] == "user@t.test"
    assert (
        client.post(
            "/api/auth/login", data={"username": "9876543210", "password": "nope-nope"}
        ).status_code
        == 401
    )
    # Email login still works, and /me reports the phone.
    hu = _login(client, _USER)
    assert client.get("/api/auth/me", headers=hu).json()["phone"] == "+919876543210"
    # The same number cannot go on a second account.
    r = client.patch("/api/users/admin@t.test/phone", json={"phone": "9876543210"}, headers=h)
    assert r.status_code == 409
    r = client.post(
        "/api/users",
        json={"email": "new@t.test", "password": "New-pass-123", "phone": "9876543210"},
        headers=h,
    )
    assert r.status_code == 409
    # Garbage is refused; a user can set/clear their own number.
    assert (
        client.patch("/api/users/user@t.test/phone", json={"phone": "12"}, headers=h).status_code
        == 400
    )
    r = client.patch("/api/auth/me/phone", json={"phone": "+91 91234 56789"}, headers=hu)
    assert r.status_code == 200 and r.json()["phone"] == "+919123456789"
    assert (
        client.patch("/api/auth/me/phone", json={"phone": ""}, headers=hu).json()["phone"] is None
    )
    assert (
        client.post(
            "/api/auth/login", data={"username": "9123456789", "password": _USER[1]}
        ).status_code
        == 401
    )
    # Users list carries the phone column; admins see it too.
    r = client.post(
        "/api/users",
        json={"email": "ph@t.test", "password": "New-pass-123", "phone": "+91 9000000001"},
        headers=h,
    )
    assert r.status_code == 201 and r.json()["phone"] == "+919000000001"
    rows = {u["email"]: u for u in client.get("/api/users", headers=_login(client, _ADMIN)).json()}
    assert rows["ph@t.test"]["phone"] == "+919000000001"
