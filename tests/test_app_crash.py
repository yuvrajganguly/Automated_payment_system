"""Crash reports from the recruiter app (2026-09-07).

There is no logcat on a recruiter's phone, so the app posts its own start-up
breadcrumb trail — and the stack trace when there was one — to
`POST /app/crash`. Unauthenticated by necessity: the crash usually happens
before anyone can sign in. Reading them back is admin-only.
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


@pytest.fixture
def client(db):
    for email, pw, role in (_ADMIN, _REC):
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


def test_a_phone_can_report_without_signing_in(db, client):
    r = client.post(
        "/api/app/crash",
        json={
            "version": "0.1.0-debug",
            "device": "realme RMX3771",
            "android": "14 (API 34)",
            "kind": "crash",
            "trail": "app.attach\napp.create\n",
            "detail": "java.lang.IllegalStateException: boom\n\tat com.qwikserve…",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["stored"] is True
    row = db.execute("SELECT * FROM app_crashes ORDER BY id DESC LIMIT 1").fetchone()
    assert row["device"] == "realme RMX3771" and row["kind"] == "crash"
    assert "boom" in row["detail"] and "app.create" in row["trail"]


def test_only_admins_read_them_back(db, client):
    client.post("/api/app/crash", json={"kind": "trail", "trail": "app.attach\n"})
    assert client.get("/api/app/crashes", headers=_login(client, _REC)).status_code == 403
    rows = client.get("/api/app/crashes", headers=_login(client, _ADMIN)).json()
    assert len(rows) == 1 and rows[0]["kind"] == "trail"


def test_junk_is_capped_not_rejected(db, client):
    # A phone in trouble should never be argued with; it is trimmed instead.
    r = client.post(
        "/api/app/crash",
        json={"kind": "nonsense", "detail": "x" * 40_000, "trail": "y" * 20_000},
    )
    assert r.status_code == 422  # over the field cap, the phone re-sends trimmed
    r = client.post("/api/app/crash", json={"kind": "nonsense", "detail": "x" * 5_000})
    assert r.status_code == 201
    row = db.execute("SELECT kind, detail FROM app_crashes ORDER BY id DESC LIMIT 1").fetchone()
    assert row["kind"] == "crash"  # unknown kinds are filed as crashes
    assert len(row["detail"]) == 5_000
