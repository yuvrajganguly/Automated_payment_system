"""End-to-end API smoke test — every GET endpoint returns 200.

The domain suite tests the engine, not the HTTP routes, so route-layer SQL
regressions (especially SQLite-vs-PostgreSQL dialect differences) slip through.
This test boots the real app, seeds the demo fleet, logs in, and hits every GET
endpoint plus every dashboard breakdown metric.

It asserts ``== 200`` (not just "no 5xx"): a 401 from a broken cookie or a 404
for every id used to pass silently. Path parameters are filled from the demo
seed; a path that still contains ``{`` fails the test instead of being skipped.

Backend-agnostic: runs on SQLite by default; set ``PAYOUT_DB_URL`` to a Postgres
URL (database name ending in ``_test``) to run the same checks against Postgres.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from payout.api import ratelimit  # noqa: E402
from payout.config import DB_URL  # noqa: E402
from payout.db import get_connection, initialize_database  # noqa: E402
from payout.db.demo_seed import seed_demo  # noqa: E402
from tests.conftest import reset_database  # noqa: E402

_BREAKDOWN_METRICS = [
    "active_riders",
    "inactive_riders",
    "rent_expected",
    "provider_owed",
    "active_evs",
    "inactive_evs",
    "untouched_evs",
    "rent_collected",
    "rent_missed",
    "rent_pending",
    "rent_partial",
    "arrears_recovered",
    "manual_rent",
    "cod",
    "hold",
    "payout",
    "total_arrears",
]

# Required query strings, per OpenAPI path.
_QUERY = {
    "/api/riders/{rider_id}": "company={rider_company}",
    "/api/dashboard/story/by": "dim=company",
    "/api/providers/{provider}/period": "date_from=2026-08-10&date_to=2026-08-30",
    "/api/providers/{provider}/reconciliation": "date_from=2026-08-10&date_to=2026-08-30",
    "/api/providers/{provider}/reconciliation/export": "date_from=2026-08-10&date_to=2026-08-30",
}

# GETs that legitimately answer something other than 200 with these params.
_EXPECTED_STATUS = {
    "/api/providers/{provider}/bills/{bill_id}": 404,  # no bills in the demo seed
    "/api/payments/uploads/{upload_id}": 404,  # no MIS uploads in the demo seed
    "/api/documents/{doc_id}/download": 404,  # no documents in the demo seed
}
if DB_URL:
    # No single file to stream on Postgres; the route says to use pg_dump.
    _EXPECTED_STATUS["/api/creator/system/backup"] = 501


@pytest.fixture(scope="module")
def smoke():
    """A logged-in TestClient over a freshly demo-seeded database."""
    from payout.api.app import _seed_demo_users, app

    reset_database()
    initialize_database()
    _seed_demo_users()
    with get_connection() as conn:
        seed_demo(conn)
        # The creator-only routes (/api/creator/*) must be exercised too.
        conn.execute("UPDATE users SET role='creator' WHERE email='admin@demo.com'")
        conn.commit()
    ratelimit.reset()
    # raise_server_exceptions=False so a 500 comes back as a response we can
    # assert on, instead of propagating and aborting the whole test.
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.post(
            "/api/auth/login", data={"username": "admin@demo.com", "password": "Demo-1234"}
        )
        assert r.status_code == 200, f"demo login failed: {r.status_code} {r.text[:200]}"
        with get_connection() as conn:
            pid = conn.execute("SELECT person_id FROM person_registry LIMIT 1").fetchone()[0]
            ev = conn.execute("SELECT ev_id FROM ev_units LIMIT 1").fetchone()[0]
            rider, company = conn.execute(
                "SELECT rider_id, company FROM rider_master LIMIT 1"
            ).fetchone()
            provider = conn.execute("SELECT provider FROM ev_models LIMIT 1").fetchone()[0]
        subs = {
            "{person_id}": str(pid),
            "{ev_id}": str(ev),
            "{rider_id}": str(rider),
            "{company_name}": company,
            "{rider_company}": company,
            "{provider}": provider,
            "{email}": "admin@demo.com",
            "{upload_id}": "1",
            "{bill_id}": "1",
            "{doc_id}": "1",
            "{request_id}": "1",
        }
        yield client, app, subs


def _fill(template: str, subs: dict[str, str]) -> str:
    for k, v in subs.items():
        template = template.replace(k, v)
    return template


def test_all_get_endpoints_return_200(smoke):
    client, app, subs = smoke
    failures = []
    for path, methods in app.openapi()["paths"].items():
        if "get" not in methods or "{metric}" in path:
            continue
        url = _fill(path, subs)
        if "{" in url:
            failures.append(f"{path}: unresolved path parameter — add it to subs")
            continue
        if path in _QUERY:
            url += "?" + _fill(_QUERY[path], subs)
        r = client.get(url)
        want = _EXPECTED_STATUS.get(path, 200)
        if r.status_code != want:
            failures.append(f"{url} -> {r.status_code} (wanted {want}): {r.text[:160]}")
    assert not failures, "GET endpoints:\n" + "\n".join(failures)


def test_dashboard_breakdowns_return_200(smoke):
    client, _app, _subs = smoke
    failures = []
    for metric in _BREAKDOWN_METRICS:
        r = client.get(f"/api/dashboard/breakdown/{metric}")
        if r.status_code != 200:
            failures.append(f"{metric} -> {r.status_code}: {r.text[:160]}")
    assert not failures, "dashboard breakdown metrics:\n" + "\n".join(failures)
