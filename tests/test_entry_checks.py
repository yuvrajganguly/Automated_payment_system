"""Refusing a bad record at the point of entry (2026-09-19).

Three typos reached live data in September 2026 and each one was found weeks
later in a reconciliation, by which time rent had been charged against a
vehicle or a rider that does not exist. Every case below is one of those,
replayed against the checks that now stand in the way.

The counter-cases matter as much: a recruiter in the field who cannot add the
bike in his hands, or the second man genuinely called Bidhan Mondal, is a
worse outcome than the typo. Each block here has a way through that a human
takes deliberately.
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
_RECRUITER = ("rec@t.test", "Recruit-pass-1", "recruiter")


@pytest.fixture
def client(db):
    for email, pw, role in (_ADMIN, _RECRUITER):
        db.execute(
            "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
            (email, hash_password(pw), role),
        )
    db.commit()
    ratelimit.reset()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _login(client, who=_ADMIN):
    email, pw, _ = who
    r = client.post("/api/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _add_ev(client, h, ev_id, provider="Raft", model="Blue"):
    return client.post(
        "/api/evs", json={"ev_id": ev_id, "provider": provider, "model": model}, headers=h
    )


# ── EV ids ───────────────────────────────────────────────────────────────────
def test_the_september_phantoms_are_both_refused(client):
    """CBJCEVD0250 (J for I) and CBICEVDO286 (letter O for zero) are the two
    units that actually reached the database on 12 September."""
    h = _login(client)
    assert _add_ev(client, h, "CBICEVD0250").status_code == 201
    assert _add_ev(client, h, "CBICEVD0286").status_code == 201

    bad = _add_ev(client, h, "CBJCEVD0250")
    assert bad.status_code == 409
    assert "CBICEVD" in bad.json()["detail"]

    bad = _add_ev(client, h, "CBICEVDO286")
    assert bad.status_code == 409
    assert "CBICEVD0286" in bad.json()["detail"], "the message must name what it collided with"

    assert client.get("/api/evs", headers=h).json().__len__() == 2


def test_a_real_new_vehicle_is_not_blocked(client):
    h = _login(client)
    assert _add_ev(client, h, "CBICEVD0250").status_code == 201
    assert _add_ev(client, h, "CBICEVD0299").status_code == 201


def test_an_exact_repeat_still_says_already_exists(client):
    """Not "looks like a typo" — it is not a typo, it is the same vehicle."""
    h = _login(client)
    assert _add_ev(client, h, "CBICEVD0250").status_code == 201
    r = _add_ev(client, h, "CBICEVD0250")
    assert r.status_code == 409
    assert "already exists" in r.json()["detail"]


def test_a_model_with_no_known_prefix_only_gets_the_confusable_check(client):
    """Raft Regular's pattern is not known, and inventing one would refuse
    real vehicles. The fold still applies."""
    h = _login(client)
    assert _add_ev(client, h, "ANYTHING-123", model="Regular").status_code == 201
    r = _add_ev(client, h, "ANYTH1NG-123", model="Regular")
    assert r.status_code == 409


# ── duplicate people ─────────────────────────────────────────────────────────
def _add_rider(client, h, **kw):
    body = {"company": "Jiffy", "name": "Somebody", **kw}
    return client.post("/api/riders", json=body, headers=h)


def test_the_same_man_at_a_second_company_is_refused(client):
    """Suman Mondal, exactly: the office had him at Jiffy, the recruiter added
    him at Myntra. The per-company check could not see it — that is what this
    cross-company one is for."""
    h = _login(client)
    assert (
        _add_rider(client, h, name="Suman Mondal", company="Jiffy", mob_no="8910797718").status_code
        == 201
    )
    r = _add_rider(client, h, name="Suman Mondal", company="Myntra", mob_no="8910797718")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "Suman Mondal" in detail
    assert "phone=8910797718" in detail


def test_a_spelling_difference_does_not_get_past_it(client):
    """SUSANTA GHOSH and Sushanta ghosh are one man; an exact-name check said
    they were two."""
    h = _login(client)
    assert (
        _add_rider(
            client, h, name="SUSANTA GHOSH", company="Jiffy", account_no="110212303478"
        ).status_code
        == 201
    )
    r = _add_rider(client, h, name="Sushanta ghosh", company="Myntra", account_no="110212303478")
    assert r.status_code == 409


def test_two_different_men_with_one_name_are_both_allowed(client):
    """No shared phone, no shared account. Blocking this would strand a real
    rider, and it is the commonest case of all."""
    h = _login(client)
    assert (
        _add_rider(
            client, h, name="Bidhan Mondal", company="Jiffy", mob_no="9000000001"
        ).status_code
        == 201
    )
    assert (
        _add_rider(
            client, h, name="Bidhan Mondal", company="Myntra", mob_no="9000000002"
        ).status_code
        == 201
    )


def test_the_office_can_override_a_strong_match(client):
    h = _login(client)
    _add_rider(client, h, name="Amir Ali", company="Jiffy", mob_no="9000000003")
    r = _add_rider(client, h, name="Amir Ali", company="Myntra", mob_no="9000000003")
    assert r.status_code == 409
    r = _add_rider(
        client,
        h,
        name="Amir Ali",
        company="Myntra",
        mob_no="9000000003",
        confirm_new_person=True,
    )
    assert r.status_code == 201, r.text


def test_allow_duplicate_name_does_not_wave_through_a_shared_phone(client):
    """The old flag means "two riders here share a name". An old client
    sending it must not thereby bypass a check it has never heard of."""
    h = _login(client)
    _add_rider(client, h, name="Kazi Hossain", company="Jiffy", mob_no="9000000004")
    r = _add_rider(
        client,
        h,
        name="Kazi Hossain",
        company="Myntra",
        mob_no="9000000004",
        allow_duplicate_name=True,
    )
    assert r.status_code == 409


def test_adding_a_known_person_to_a_second_company_is_never_blocked(client):
    """Naming the person IS the statement that it is the same man — which is
    the thing we are asking for, so it must not be harder than the mistake."""
    h = _login(client)
    first = _add_rider(client, h, name="Jeet Kumar Ghosh", company="Jiffy", mob_no="9000000005")
    pid = first.json()["person_id"]
    r = _add_rider(
        client,
        h,
        name="Jeet Kumar Ghosh",
        company="Myntra",
        mob_no="9000000005",
        person_id=pid,
    )
    assert r.status_code == 201, r.text


# ── asking before submitting ─────────────────────────────────────────────────
def test_the_precheck_answers_before_anything_is_created(client):
    h = _login(client)
    _add_rider(client, h, name="Pritam Biswas", company="Jiffy", mob_no="9000000006")

    r = client.get(
        "/api/riders/duplicate-check",
        params={"name": "Pritam Biswas", "mob_no": "9000000006"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["blocking"] is True
    assert body["matches"][0]["display_name"] == "Pritam Biswas"
    assert "phone=9000000006" in body["matches"][0]["evidence"]

    # Same name, different phone: worth showing, not worth refusing.
    r = client.get(
        "/api/riders/duplicate-check",
        params={"name": "Pritam Biswas", "mob_no": "9999999999"},
        headers=h,
    )
    assert r.json()["blocking"] is False
    assert r.json()["matches"][0]["evidence"] == "same name only"

    r = client.get("/api/riders/duplicate-check", params={"name": "Nobody Here"}, headers=h)
    assert r.json() == {"matches": [], "blocking": False}


def test_a_recruiter_can_run_the_precheck(client):
    """It is the recruiter in the field who needs the answer."""
    h = _login(client, _RECRUITER)
    r = client.get("/api/riders/duplicate-check", params={"name": "Anyone"}, headers=h)
    assert r.status_code == 200


# ── the timeline ─────────────────────────────────────────────────────────────
def test_the_timeline_shows_the_money_alongside_the_actions(client, db):
    """ "Why was he charged twice" is not answerable from a list of who pressed
    which button. The ledger was the half that was missing."""
    from tests.conftest import make_person, make_rider

    h = _login(client)
    pid = make_person(db, "Moti Mondal")
    make_rider(db, pid, "R-1", "Jiffy", "Moti Mondal")
    db.execute(
        "INSERT INTO activity_log (at, email, action, entity_type, entity_id, person_id) "
        "VALUES ('2026-09-08 10:00:00', 'rec@t.test', 'rider.create', 'rider', 'R-1@Jiffy', ?)",
        (pid,),
    )
    db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, created_at) VALUES "
        "(?, 'R-1', 'Jiffy', '2026-09-08', '2026-09-14', 'RENT', -129500, -129500, "
        "'2026-09-15 06:00:00')",
        (pid,),
    )
    db.commit()

    r = client.get(f"/api/app/person/{pid}/timeline", headers=h)
    assert r.status_code == 200, r.text
    rows = r.json()
    assert [x["source"] for x in rows] == ["money", "activity"], "newest first, interleaved"
    money = rows[0]
    assert money["action_label"] == "Rent"
    # Paise on the way in, rupees on the way out — the middleware finds
    # `amount` inside details.
    assert money["details"]["amount"] == -1295.0
    assert money["details"]["cycle"] == "2026-09-08 → 2026-09-14"
