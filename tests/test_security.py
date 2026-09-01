"""Security regressions found in the 2026-09-01 review.

Every test here is a "this used to be possible" case:
- a plain `user` could commit a payout cycle;
- the login body (with the password) was written verbatim to audit_log;
- demo accounts were created on any deployment by default;
- a deactivated user's token kept working for 12 hours;
- a wrong OTP guess did not consume the code, so it could be brute-forced.
"""
from __future__ import annotations

import io

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from payout.api import ratelimit  # noqa: E402
from payout.api.app import _seed_demo_users, app  # noqa: E402
from payout.auth import hash_password  # noqa: E402
from payout.db import get_connection  # noqa: E402

_ADMIN = ("admin@t.test", "Admin-pass-1", "admin")
_USER = ("user@t.test", "User-pass-1", "user")


def _add_users(db, *users):
    for email, pw, role in users:
        db.execute(
            "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
            (email, hash_password(pw), role),
        )
    db.commit()


@pytest.fixture
def client(db):
    _add_users(db, _ADMIN, _USER)
    ratelimit.reset()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _login(client, email, pw):
    r = client.post("/api/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _tiny_xlsx() -> bytes:
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["rider_id", "net_pay", "total_del"])
    ws.append(["R1", 1000, 3])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── authorization ────────────────────────────────────────────────────────────


def test_plain_user_cannot_run_a_cycle(client):
    tok = _login(client, _USER[0], _USER[1])
    r = client.post(
        "/api/cycles/run",
        headers={"Authorization": f"Bearer {tok}"},
        data={"company": "Blitz", "cycle_start": "2026-06-01",
              "cycle_end": "2026-06-07", "commit": "true"},
        files={"file": ("blitz.xlsx", _tiny_xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 403
    with get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_admin_can_preview_a_cycle(client):
    tok = _login(client, _ADMIN[0], _ADMIN[1])
    r = client.post(
        "/api/cycles/run",
        headers={"Authorization": f"Bearer {tok}"},
        data={"company": "Blitz", "cycle_start": "2026-06-01",
              "cycle_end": "2026-06-07", "commit": "false"},
        files={"file": ("blitz.xlsx", _tiny_xlsx(),
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text


def test_every_mutating_route_requires_auth(client):
    """No POST/PATCH/PUT/DELETE may answer anything but 401 to an anonymous caller
    (except the auth entry points themselves)."""
    anon_ok = {"/api/auth/login", "/api/auth/logout", "/api/auth/forgot-password",
               "/api/auth/reset-password"}
    offenders = []
    for path, methods in app.openapi()["paths"].items():
        for method in ("post", "patch", "put", "delete"):
            if method not in methods or path in anon_ok:
                continue
            url = path.replace("{person_id}", "1").replace("{ev_id}", "X")
            url = url.replace("{rider_id}", "R").replace("{company_name}", "Blitz")
            url = url.replace("{provider}", "Raft").replace("{bill_id}", "1")
            url = url.replace("{upload_id}", "1").replace("{email}", "x@y.z")
            url = url.replace("{model_id}", "1").replace("{txn_id}", "1").replace("{id}", "1")
            r = getattr(client, method)(url)
            if r.status_code != 401:
                offenders.append(f"{method.upper()} {url} -> {r.status_code}")
    assert not offenders, "\n".join(offenders)


# ── audit log ────────────────────────────────────────────────────────────────


def test_login_body_is_never_stored_in_audit_log(client):
    _login(client, _ADMIN[0], _ADMIN[1])
    client.post("/api/auth/login", data={"username": _ADMIN[0], "password": "wrong-guess"})
    with get_connection() as c:
        rows = c.execute(
            "SELECT body_excerpt FROM audit_log WHERE path LIKE '/api/auth/%'"
        ).fetchall()
    assert rows, "auth requests should still be audited (without their body)"
    for (excerpt,) in rows:
        assert not excerpt, f"credentials leaked into audit_log: {excerpt!r}"


def test_scrub_handles_json_and_form_bodies():
    from payout.api.middleware import _scrub

    assert _scrub('{"email":"a@b","password":"s3cret"}') == '{"email":"a@b","password":"***"}'
    assert _scrub("username=a%40b&password=s3cret&x=1") == "username=a%40b&password=***&x=1"
    assert _scrub('{"otp":"123456","new_password":"pw"}') == '{"otp":"***","new_password":"***"}'


# ── demo seeding ─────────────────────────────────────────────────────────────


def test_demo_users_are_not_created_when_real_users_exist(db):
    _add_users(db, _ADMIN)
    assert _seed_demo_users() is False
    assert db.execute(
        "SELECT COUNT(*) FROM users WHERE email LIKE '%@demo.com'"
    ).fetchone()[0] == 0


def test_demo_users_are_created_on_an_empty_user_table(db):
    assert _seed_demo_users() is True
    assert db.execute(
        "SELECT COUNT(*) FROM users WHERE email LIKE '%@demo.com'"
    ).fetchone()[0] == 2


def test_demo_mode_is_opt_in(monkeypatch):
    import importlib

    monkeypatch.delenv("PAYOUT_SEED_DEMO", raising=False)
    import payout.api.config as cfg

    importlib.reload(cfg)
    assert cfg.DEMO_MODE is False


def test_health_reports_demo_flag(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "demo": False}


# ── sessions follow the database, not the token ──────────────────────────────


def test_deactivated_user_token_stops_working_immediately(client):
    tok = _login(client, _USER[0], _USER[1])
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).status_code == 200
    with get_connection() as c:
        c.execute("UPDATE users SET is_active=0 WHERE email=?", (_USER[0],))
        c.commit()
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 401


def test_role_change_applies_on_next_request(client):
    tok = _login(client, _USER[0], _USER[1])
    with get_connection() as c:
        c.execute("UPDATE users SET role='admin' WHERE email=?", (_USER[0],))
        c.commit()
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"})
    assert r.json()["role"] == "admin"


# ── OTP reset ────────────────────────────────────────────────────────────────


def test_otp_is_locked_after_five_wrong_guesses(client, monkeypatch):
    monkeypatch.setenv("PAYOUT_DEV_PRINT_EMAIL", "1")
    import payout.api.routes.auth as auth_routes

    captured = {}
    monkeypatch.setattr(
        auth_routes, "send_email",
        lambda to, subject, body: captured.setdefault("body", body) or True,
    )
    r = client.post("/api/auth/forgot-password", json={"email": _USER[0]})
    assert r.status_code == 200, r.text
    real_otp = captured["body"].split("code is:")[1].split()[0]

    wrong = "000000" if real_otp != "000000" else "111111"
    for i in range(4):
        r = client.post("/api/auth/reset-password",
                        json={"email": _USER[0], "otp": wrong, "new_password": "New-pass-99"})
        assert r.status_code == 401 and "Incorrect" in r.text, (i, r.text)
    r = client.post("/api/auth/reset-password",
                    json={"email": _USER[0], "otp": wrong, "new_password": "New-pass-99"})
    assert r.status_code == 401 and "Too many" in r.text
    # Even the right code is dead now.
    r = client.post("/api/auth/reset-password",
                    json={"email": _USER[0], "otp": real_otp, "new_password": "New-pass-99"})
    assert r.status_code == 400
    # and the password did not change
    assert client.post("/api/auth/login",
                       data={"username": _USER[0], "password": _USER[1]}).status_code == 200


def test_forgot_password_refuses_when_email_is_not_configured(client, monkeypatch):
    monkeypatch.delenv("PAYOUT_DEV_PRINT_EMAIL", raising=False)
    monkeypatch.delenv("PAYOUT_SMTP_HOST", raising=False)
    r = client.post("/api/auth/forgot-password", json={"email": _USER[0]})
    assert r.status_code == 503
    with get_connection() as c:
        assert c.execute("SELECT COUNT(*) FROM password_reset_tokens").fetchone()[0] == 0


def test_login_is_rate_limited(client):
    for _ in range(20):
        client.post("/api/auth/login", data={"username": "nobody@t.test", "password": "x"})
    r = client.post("/api/auth/login", data={"username": "nobody@t.test", "password": "x"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers
