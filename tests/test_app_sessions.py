"""Refresh tokens: the recruiter app stays signed in without a password."""

from __future__ import annotations

import pytest

from payout.auth.sessions import _hash


@pytest.fixture
def client(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    db.executemany(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        [
            ("rec@t.test", hash_password("Recruit-pass-1"), "recruiter"),
            ("boss@t.test", hash_password("Creator-pass-1"), "creator"),
        ],
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        yield c


def _app_login(client, email="rec@t.test", pw="Recruit-pass-1"):
    r = client.post(
        "/api/auth/login",
        data={"username": email, "password": pw, "device": "android Pixel 7"},
    )
    assert r.status_code == 200, r.text
    return r.json()


def test_web_login_gets_no_refresh_token(client):
    r = client.post(
        "/api/auth/login", data={"username": "rec@t.test", "password": "Recruit-pass-1"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["refresh_token"] is None and body["expires_in"] == 12 * 3600
    assert "payout_auth" in r.cookies or len(r.cookies) >= 1  # cookie set for browsers


def test_app_login_refresh_rotates_and_reuse_revokes_everything(db, client):
    body = _app_login(client)
    assert body["refresh_token"].startswith("qrt_") and body["role"] == "recruiter"
    rt1 = body["refresh_token"]
    # Stored hashed, never plain.
    row = db.execute("SELECT token_hash, client FROM refresh_tokens").fetchone()
    assert row["token_hash"] == _hash(rt1) and rt1 not in row["token_hash"]
    assert row["client"] == "android Pixel 7"
    # Access token works.
    me = client.get("/api/auth/me", headers={"Authorization": "Bearer " + body["access_token"]})
    assert me.status_code == 200 and me.json()["email"] == "rec@t.test"

    # Refresh: new pair, old refresh retired.
    r = client.post("/api/auth/refresh", json={"refresh_token": rt1})
    assert r.status_code == 200, r.text
    rt2 = r.json()["refresh_token"]
    assert rt2 != rt1 and r.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": "Bearer " + r.json()["access_token"]})
    assert me.status_code == 200

    # Presenting the retired token again = a copy exists: everything revoked.
    r = client.post("/api/auth/refresh", json={"refresh_token": rt1})
    assert r.status_code == 401 and "elsewhere" in r.json()["detail"]
    r = client.post("/api/auth/refresh", json={"refresh_token": rt2})
    assert r.status_code == 401
    assert (
        db.execute("SELECT COUNT(*) FROM refresh_tokens WHERE revoked_at IS NULL").fetchone()[0]
        == 0
    )


def test_unknown_expired_and_logged_out_tokens(db, client):
    assert client.post("/api/auth/refresh", json={"refresh_token": "qrt_nope"}).status_code == 401
    rt = _app_login(client)["refresh_token"]
    # Logout from the phone revokes it.
    assert client.post("/api/auth/logout", json={"refresh_token": rt}).status_code == 200
    r = client.post("/api/auth/refresh", json={"refresh_token": rt})
    assert r.status_code == 401 and "signed out" in r.json()["detail"]
    # Expired.
    rt = _app_login(client)["refresh_token"]
    db.execute(
        "UPDATE refresh_tokens SET expires_at='2020-01-01T00:00:00' WHERE token_hash=?",
        (_hash(rt),),
    )
    db.commit()
    r = client.post("/api/auth/refresh", json={"refresh_token": rt})
    assert r.status_code == 401 and "expired" in r.json()["detail"]
    # Plain logout without a body still works for the web.
    assert client.post("/api/auth/logout").status_code == 200


def test_password_change_set_and_deactivation_revoke_sessions(db, client):
    body = _app_login(client)
    rt = body["refresh_token"]
    hdr = {"Authorization": "Bearer " + body["access_token"]}
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": "Recruit-pass-1", "new_password": "Recruit-pass-2"},
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    assert client.post("/api/auth/refresh", json={"refresh_token": rt}).status_code == 401

    rt = _app_login(client, pw="Recruit-pass-2")["refresh_token"]
    boss = client.post(
        "/api/auth/login", data={"username": "boss@t.test", "password": "Creator-pass-1"}
    ).json()["access_token"]
    bh = {"Authorization": "Bearer " + boss}
    r = client.patch(
        "/api/users/rec@t.test/password", json={"new_password": "Recruit-pass-3"}, headers=bh
    )
    assert r.status_code == 200, r.text
    assert client.post("/api/auth/refresh", json={"refresh_token": rt}).status_code == 401

    rt = _app_login(client, pw="Recruit-pass-3")["refresh_token"]
    r = client.post("/api/users/rec@t.test/sign-out-everywhere", headers=bh)
    assert r.status_code == 200 and r.json()["sessions_revoked"] == 1
    assert client.post("/api/auth/refresh", json={"refresh_token": rt}).status_code == 401

    rt = _app_login(client, pw="Recruit-pass-3")["refresh_token"]
    assert client.patch("/api/users/rec@t.test/deactivate", headers=bh).status_code == 200
    r = client.post("/api/auth/refresh", json={"refresh_token": rt})
    assert r.status_code == 401
    reasons = {r["revoke_reason"] for r in db.execute("SELECT revoke_reason FROM refresh_tokens")}
    assert any(x and x.startswith("deactivated by") for x in reasons)


def test_self_logout_everywhere(db, client):
    a = _app_login(client)
    b = _app_login(client)
    r = client.post(
        "/api/auth/logout-everywhere", headers={"Authorization": "Bearer " + a["access_token"]}
    )
    assert r.status_code == 200 and r.json()["sessions_revoked"] == 2
    for t in (a, b):
        assert (
            client.post("/api/auth/refresh", json={"refresh_token": t["refresh_token"]}).status_code
            == 401
        )


def test_bootstrap_riders_search_paging_and_thumb(db, client):
    from tests.conftest import make_person, make_rider

    p1 = make_person(db, "Arjun Das")
    make_rider(db, p1, "SF-1", "Shadowfax", "Arjun Das")
    db.execute(
        "UPDATE rider_master SET hub='Salt Lake', mob_no='98765 43210' WHERE rider_id='SF-1'"
    )
    p2 = make_person(db, "Bikash Roy")
    make_rider(db, p2, "SF-2", "Shadowfax", "Bikash Roy")
    make_rider(db, p2, "31111", "Kaptan", "Bikash Roy")
    db.commit()
    hdr = {"Authorization": "Bearer " + _app_login(client)["access_token"]}

    b = client.get("/api/app/bootstrap", headers=hdr)
    assert b.status_code == 200, b.text
    body = b.json()
    assert body["me"]["role"] == "recruiter" and body["api_version"] >= 1
    assert "Shadowfax" in {c["company_name"] for c in body["companies"]}
    assert body["hubs"] == ["Salt Lake"]
    assert body["counts"]["rider_ids_active"] == 3 and body["counts"]["persons_active"] == 2
    assert "evs" in body["counts"] and "amount" not in str(body)  # no money here

    # Search across name / id / phone / hub, any case.
    for q, expect in [
        ("arjun", 1),
        ("sf-", 2),
        ("43210", 1),
        ("salt", 1),
        ("bikash", 2),
        ("zzz", 0),
    ]:
        r = client.get(f"/api/riders?q={q}", headers=hdr)
        assert r.status_code == 200 and len(r.json()) == expect, (q, r.json())
        assert r.headers["X-Total-Count"] == str(expect)
    # Paging: total counts the whole match, rows are the page.
    r = client.get("/api/riders?limit=2&offset=0", headers=hdr)
    assert len(r.json()) == 2 and r.headers["X-Total-Count"] == "3"
    r = client.get("/api/riders?limit=2&offset=2", headers=hdr)
    assert len(r.json()) == 1
    assert client.get("/api/riders?limit=0", headers=hdr).status_code == 422

    # Thumbnail: 404 without a photo; a 160px square JPEG with one.
    assert client.get(f"/api/persons/{p1}/photo?size=thumb", headers=hdr).status_code == 404
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (900, 600), (200, 30, 30)).save(buf, format="PNG")
    r = client.post(
        f"/api/persons/{p1}/documents",
        data={"doc_type": "photo"},
        files={"file": ("face.png", buf.getvalue(), "image/png")},
        headers=hdr,
    )
    assert r.status_code == 201, r.text
    r = client.get(f"/api/persons/{p1}/photo?size=thumb", headers=hdr)
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    im = Image.open(io.BytesIO(r.content))
    assert im.size == (160, 160)
    full = client.get(f"/api/persons/{p1}/photo", headers=hdr)
    assert full.status_code == 200 and len(full.content) > len(r.content)
