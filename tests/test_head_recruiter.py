"""Head recruiter for a zone (2026-09-11).

A flag on a recruiter account, not a rung on the ladder. ``ROLE_RANK`` is
load-bearing in the money fence and in who-may-act-on-whom, so a head stays a
``recruiter`` for every permission check in the codebase. What the flag adds is
sight of what the other recruiters in their own zone have done — and nothing
else. These tests are mostly about the "and nothing else".
"""

from __future__ import annotations

import pytest

from tests.conftest import make_person, make_rider


@pytest.fixture
def client(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    db.executemany(
        "INSERT INTO users (email, password_hash, role, is_active, zone) VALUES (?,?,?,1,?)",
        [
            ("head-n@t.test", hash_password("Recruit-pass-1"), "recruiter", "North"),
            ("rec-n@t.test", hash_password("Recruit-pass-2"), "recruiter", "North"),
            ("rec-s@t.test", hash_password("Recruit-pass-3"), "recruiter", "South"),
            ("head-s@t.test", hash_password("Recruit-pass-4"), "recruiter", "South"),
            ("boss@t.test", hash_password("Creator-pass-1"), "creator", None),
        ],
    )
    db.execute("UPDATE users SET is_head=1 WHERE email IN ('head-n@t.test','head-s@t.test')")
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        yield c


def _hdr(client, email, pw):
    r = client.post("/api/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


@pytest.fixture
def staff(client):
    return {
        "head_n": _hdr(client, "head-n@t.test", "Recruit-pass-1"),
        "rec_n": _hdr(client, "rec-n@t.test", "Recruit-pass-2"),
        "rec_s": _hdr(client, "rec-s@t.test", "Recruit-pass-3"),
        "head_s": _hdr(client, "head-s@t.test", "Recruit-pass-4"),
        "boss": _hdr(client, "boss@t.test", "Creator-pass-1"),
    }


def _onboard(client, hdr, name, rider_id, company="Shadowfax"):
    r = client.post(
        "/api/riders",
        json={"company": company, "name": name, "rider_id": rider_id},
        headers=hdr,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


# ── what the flag grants ─────────────────────────────────────────────────────


def test_the_head_sees_their_zones_recruiters(client, staff):
    _onboard(client, staff["rec_n"], "Arjun Das", "SF-1")
    _onboard(client, staff["rec_n"], "Bikash Roy", "SF-2")
    _onboard(client, staff["head_n"], "Chandan Sen", "SF-3")
    _onboard(client, staff["rec_s"], "Dipak Roy", "SF-4")

    board = client.get("/api/app/zone-recruiting", headers=staff["head_n"]).json()
    assert board["zone"] == "North"
    rows = {r["email"]: r for r in board["recruiters"]}
    assert set(rows) == {"head-n@t.test", "rec-n@t.test"}, "South is somebody else's problem"
    assert rows["rec-n@t.test"]["all_time"] == 2
    assert rows["head-n@t.test"]["all_time"] == 1
    assert board["totals"]["all_time"] == 3


def test_the_head_can_drill_into_one_of_theirs(client, staff):
    _onboard(client, staff["rec_n"], "Arjun Das", "SF-1")
    r = client.get("/api/app/my-recruiting?email=rec-n@t.test", headers=staff["head_n"])
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "rec-n@t.test"
    assert r.json()["counts"]["all_time"] == 1


def test_the_head_can_read_their_recruiters_record(client, staff):
    """The /recruiters/{email}/... family shares one gate, so the whole
    supervision surface widens together: profile, riders, EVs, shifts, series."""
    _onboard(client, staff["rec_n"], "Arjun Das", "SF-1")
    for path in (
        "/api/recruiters/rec-n@t.test/profile",
        "/api/recruiters/rec-n@t.test/riders",
        "/api/recruiters/rec-n@t.test/evs",
        "/api/recruiters/rec-n@t.test/series",
    ):
        assert client.get(path, headers=staff["head_n"]).status_code == 200, path


# ── and what it does not ─────────────────────────────────────────────────────


def test_the_head_cannot_see_the_other_zone(client, staff):
    assert (
        client.get("/api/app/my-recruiting?email=rec-s@t.test", headers=staff["head_n"]).status_code
        == 403
    )
    assert (
        client.get("/api/recruiters/rec-s@t.test/riders", headers=staff["head_n"]).status_code
        == 403
    )
    assert (
        client.get("/api/app/zone-recruiting?zone=South", headers=staff["head_n"]).status_code
        == 403
    )


def test_a_head_does_not_supervise_another_head(client, staff):
    """Two heads in one zone would otherwise read each other's records. The
    flag is for supervising field staff, not colleagues at the same level."""
    client.patch("/api/users/rec-n@t.test/head", json={"is_head": True}, headers=staff["boss"])
    assert (
        client.get("/api/app/my-recruiting?email=rec-n@t.test", headers=staff["head_n"]).status_code
        == 403
    )


def test_a_head_cannot_look_upwards(client, staff):
    assert (
        client.get("/api/app/my-recruiting?email=boss@t.test", headers=staff["head_n"]).status_code
        == 403
    )


def test_a_plain_recruiter_gets_nothing_new(client, staff):
    assert client.get("/api/app/zone-recruiting", headers=staff["rec_n"]).status_code == 403
    assert (
        client.get("/api/app/my-recruiting?email=head-n@t.test", headers=staff["rec_n"]).status_code
        == 403
    )


def test_a_head_still_cannot_see_money(client, staff, db):
    """The whole reason this is a flag and not a role: `no_recruiter` keys off
    the role, so a head is fenced off the money side exactly like their team.
    If this ever passes, the flag has become a privilege escalation."""
    pid = make_person(db, "Arjun Das", balance=-25000)
    make_rider(db, pid, "SF-1", "Shadowfax", "Arjun Das")
    db.commit()
    del pid  # the person exists so a 404 cannot be mistaken for a refusal
    for path in ("/api/arrears", "/api/cod", "/api/dashboard/summary", "/api/inactive"):
        r = client.get(path, headers=staff["head_n"])
        assert r.status_code == 403, f"{path} answered {r.status_code} to a head recruiter"


def test_a_head_obeys_the_zone_fence_on_riders(client, staff, db):
    """Supervision is not a wider roster. A head still sees only their zone's
    riders, the same as any other recruiter."""
    boss = staff["boss"]
    for rid, hub in (("SF-N", "Salt Lake"), ("SF-S", "Garia")):
        pid = make_person(db, rid)
        make_rider(db, pid, rid, "Shadowfax", rid)
        db.execute("UPDATE rider_master SET hub=? WHERE rider_id=?", (hub, rid))
    db.commit()
    client.put("/api/hubs/Shadowfax/Salt Lake", json={"zone": "North"}, headers=boss)
    client.put("/api/hubs/Shadowfax/Garia", json={"zone": "South"}, headers=boss)
    got = {r["rider_id"] for r in client.get("/api/riders", headers=staff["head_n"]).json()}
    assert got == {"SF-N"}


# ── the bootstrap tells the app whether to draw the tab ──────────────────────


def test_the_bootstrap_reports_the_flag(client, staff):
    me = client.get("/api/app/bootstrap", headers=staff["head_n"]).json()["me"]
    assert me["is_head"] is True and me["zone"] == "North"
    assert me["role"] == "recruiter", "a head is a recruiter — the app must not see a new role"
    plain = client.get("/api/app/bootstrap", headers=staff["rec_n"]).json()["me"]
    assert plain["is_head"] is False


# ── granting and removing it ─────────────────────────────────────────────────


def test_an_admin_grants_and_removes_it(client, staff, db):
    boss = staff["boss"]
    r = client.patch("/api/users/rec-n@t.test/head", json={"is_head": True}, headers=boss)
    assert r.status_code == 200 and r.json()["is_head"] is True
    assert client.get("/api/app/zone-recruiting", headers=staff["rec_n"]).status_code == 200
    r = client.patch("/api/users/rec-n@t.test/head", json={"is_head": False}, headers=boss)
    assert r.status_code == 200 and r.json()["is_head"] is False
    assert client.get("/api/app/zone-recruiting", headers=staff["rec_n"]).status_code == 403


def test_a_head_needs_a_zone_first(client, staff, db):
    """A flag that silently does nothing is worse than a refusal."""
    db.execute("UPDATE users SET zone=NULL WHERE email='rec-n@t.test'")
    db.commit()
    r = client.patch("/api/users/rec-n@t.test/head", json={"is_head": True}, headers=staff["boss"])
    assert r.status_code == 400 and "zone" in r.text.lower()


def test_only_a_recruiter_can_be_a_head(client, staff):
    r = client.patch("/api/users/boss@t.test/head", json={"is_head": True}, headers=staff["boss"])
    assert r.status_code == 400


def test_a_recruiter_cannot_promote_themselves(client, staff):
    r = client.patch("/api/users/rec-n@t.test/head", json={"is_head": True}, headers=staff["rec_n"])
    assert r.status_code == 403


def test_the_users_list_shows_who_is_a_head(client, staff):
    users = {u["email"]: u for u in client.get("/api/users", headers=staff["boss"]).json()}
    assert users["head-n@t.test"]["is_head"] is True
    assert users["rec-n@t.test"]["is_head"] is False


# ── admins ───────────────────────────────────────────────────────────────────


def test_an_admin_may_name_any_zone(client, staff):
    _onboard(client, staff["rec_s"], "Dipak Roy", "SF-4")
    r = client.get("/api/app/zone-recruiting?zone=South", headers=staff["boss"])
    assert r.status_code == 200, r.text
    assert {x["email"] for x in r.json()["recruiters"]} == {"rec-s@t.test", "head-s@t.test"}
    # …but must name one: "every zone" is the console's recruiter board.
    assert client.get("/api/app/zone-recruiting", headers=staff["boss"]).status_code == 400
    assert (
        client.get("/api/app/zone-recruiting?zone=West", headers=staff["boss"]).status_code == 400
    )


# ── the flag cannot outlive what it depends on ───────────────────────────────
#
# The app decides whether to draw the supervision tab from `is_head` alone, so
# a flag left behind on an account that no longer qualifies is not cosmetic:
# it is a tab whose own endpoint answers 403 or 400.


def test_clearing_the_zone_stands_a_head_down(client, staff, db):
    """set_head refuses a head with no zone; clearing the zone afterwards must
    not walk round that check from the other side."""
    boss = staff["boss"]
    r = client.patch("/api/users/head-n@t.test/zone", json={"zone": None}, headers=boss)
    assert r.status_code == 200, r.text
    assert r.json()["is_head"] is False
    head = _hdr(client, "head-n@t.test", "Recruit-pass-1")
    assert client.get("/api/app/bootstrap", headers=head).json()["me"]["is_head"] is False
    assert client.get("/api/app/zone-recruiting", headers=head).status_code == 403


def test_a_transfer_keeps_the_flag(client, staff):
    """North's head moved to South is South's head — that is what an office
    means by a transfer, and re-ticking a box they never untimed would be an
    odd thing to ask of whoever made the change."""
    boss = staff["boss"]
    assert (
        client.patch("/api/users/head-n@t.test/zone", json={"zone": "South"}, headers=boss).json()[
            "is_head"
        ]
        is True
    )
    head = _hdr(client, "head-n@t.test", "Recruit-pass-1")
    board = client.get("/api/app/zone-recruiting", headers=head).json()
    assert board["zone"] == "South"
    # head-s is South's other head — a peer, not somebody to supervise.
    assert {r["email"] for r in board["recruiters"]} == {"head-n@t.test", "rec-s@t.test"}


def test_moving_them_off_recruiter_stands_them_down(client, staff):
    boss = staff["boss"]
    r = client.patch("/api/users/head-n@t.test/role", json={"role": "admin"}, headers=boss)
    assert r.status_code == 200, r.text
    assert client.get("/api/users", headers=boss).json()
    users = {u["email"]: u for u in client.get("/api/users", headers=boss).json()}
    assert users["head-n@t.test"]["is_head"] is False


def test_promoting_within_recruiter_keeps_it(client, staff):
    boss = staff["boss"]
    client.patch("/api/users/head-n@t.test/role", json={"role": "recruiter"}, headers=boss)
    users = {u["email"]: u for u in client.get("/api/users", headers=boss).json()}
    assert users["head-n@t.test"]["is_head"] is True


def test_the_board_leaves_out_the_other_head(client, staff):
    """A row on the board that 403s when it is tapped is worse than no row:
    `supervises` refuses a head reading another head, so the list must agree.
    The caller's own row stays — they are in their own zone."""
    client.patch("/api/users/rec-n@t.test/head", json={"is_head": True}, headers=staff["boss"])
    _onboard(client, staff["rec_n"], "Arjun Das", "SF-1")
    board = client.get("/api/app/zone-recruiting", headers=staff["head_n"]).json()
    assert {r["email"] for r in board["recruiters"]} == {"head-n@t.test"}
    assert board["totals"]["all_time"] == 0, "totals count the rows shown, nothing hidden"


def test_an_admin_sees_the_heads_too(client, staff):
    """An admin supervises the heads, so naming a zone lists everybody in it."""
    r = client.get("/api/app/zone-recruiting?zone=North", headers=staff["boss"]).json()
    assert {x["email"] for x in r["recruiters"]} == {"head-n@t.test", "rec-n@t.test"}
