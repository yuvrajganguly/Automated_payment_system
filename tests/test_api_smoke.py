"""End-to-end API smoke test — every GET endpoint returns < 500.

The domain suite tests the engine, not the HTTP routes, so route-layer SQL
regressions (especially SQLite-vs-PostgreSQL dialect differences) slip through.
This test boots the real app, seeds the demo fleet, logs in, and hits every GET
endpoint plus every dashboard breakdown metric.

Backend-agnostic: runs on SQLite by default; set ``PAYOUT_DB_URL`` to a Postgres
URL to run the exact same checks against Postgres.
"""
from __future__ import annotations

import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from payout.config import DB_URL  # noqa: E402
from payout.db import get_connection  # noqa: E402

_BREAKDOWN_METRICS = [
    "active_riders", "inactive_riders", "rent_expected", "provider_owed",
    "active_evs", "inactive_evs", "untouched_evs", "rent_collected",
    "rent_missed", "rent_pending", "rent_partial", "arrears_recovered",
    "manual_rent", "cod", "hold", "payout", "total_arrears",
]


def _reset() -> None:
    if DB_URL:
        import psycopg
        with psycopg.connect(DB_URL, autocommit=True) as c:
            c.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    else:
        from pathlib import Path
        p = os.environ.get("PAYOUT_DB", "/tmp/pytest_payout.db")
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(p + suffix).unlink()
            except FileNotFoundError:
                pass


@pytest.fixture(scope="module")
def smoke():
    """A logged-in TestClient over a freshly demo-seeded database."""
    os.environ.setdefault("PAYOUT_JWT_SECRET", "smoke-secret")
    os.environ["PAYOUT_SEED_DEMO"] = "1"
    _reset()
    from payout.api.app import app
    # raise_server_exceptions=False so a 500 comes back as a response we can
    # assert on, instead of propagating and aborting the whole test.
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post("/api/auth/login",
                        data={"username": "admin@demo.com", "password": "Demo-1234"})
        assert r.status_code == 200, f"demo login failed: {r.status_code} {r.text[:200]}"
        with get_connection() as conn:
            pid = conn.execute(
                "SELECT person_id FROM person_registry LIMIT 1").fetchone()[0]
            ev = conn.execute("SELECT ev_id FROM ev_units LIMIT 1").fetchone()[0]
        subs = {"{person_id}": str(pid), "{id}": str(pid), "{ev_id}": str(ev),
                "{company}": "Myntra", "{email}": "admin@demo.com"}
        yield client, app, subs


def test_all_get_endpoints_no_5xx(smoke):
    client, app, subs = smoke
    failures = []
    for path, methods in app.openapi()["paths"].items():
        if "get" not in methods:
            continue
        url = path
        for k, v in subs.items():
            url = url.replace(k, v)
        if "{metric}" in url:
            continue                     # covered by the breakdown test below
        if "{" in url:
            continue                     # unresolved path params — skip
        r = client.get(url)
        if r.status_code >= 500:
            failures.append(f"{url} -> {r.status_code}: {r.text[:160]}")
    assert not failures, "GET endpoints returned 5xx:\n" + "\n".join(failures)


def test_dashboard_breakdowns_no_5xx(smoke):
    client, _app, _subs = smoke
    failures = []
    for metric in _BREAKDOWN_METRICS:
        r = client.get(f"/api/dashboard/breakdown/{metric}")
        if r.status_code >= 500:
            failures.append(f"{metric} -> {r.status_code}: {r.text[:160]}")
    assert not failures, "dashboard breakdown metrics returned 5xx:\n" + "\n".join(failures)
