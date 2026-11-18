"""Public website figures: aggregate counts only, people not rider IDs."""

from __future__ import annotations

import pytest

from payout.domain.public_stats import rider_counts
from tests.conftest import make_person, make_rider


def _seed(db):
    a = make_person(db, "Two IDs")
    make_rider(db, a, "MY1", "Myntra")
    make_rider(db, a, "BL1", "Blitz")
    b = make_person(db, "Retired")
    make_rider(db, b, "SP1", "Spencer's")
    db.execute("UPDATE rider_master SET is_active=0 WHERE rider_id='SP1'")
    c = make_person(db, "Half active")
    make_rider(db, c, "DS1", "Dealshare")
    make_rider(db, c, "DS2", "Dealshare")
    db.execute("UPDATE rider_master SET is_active=0 WHERE rider_id='DS1'")
    db.commit()


def test_counts_people_once_and_splits_active(db):
    _seed(db)
    out = rider_counts(db)
    assert out["riders_total"] == 3
    assert out["riders_active"] == 2
    assert set(out) == {"riders_total", "riders_active", "as_of"}


def test_empty_database(db):
    out = rider_counts(db)
    assert (out["riders_total"], out["riders_active"]) == (0, 0)


def test_route_is_public_cached_and_cross_origin(db):
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    from fastapi.testclient import TestClient

    from payout.api.app import app
    from payout.api.routes import public

    _seed(db)
    public.reset_cache()
    with TestClient(app) as client:
        r = client.get("/api/public/rider-stats", headers={"Origin": "https://example.org"})
        assert r.status_code == 200
        assert r.headers["access-control-allow-origin"] == "*"
        assert r.json()["riders_total"] == 3 and r.json()["riders_active"] == 2
        assert "Two IDs" not in r.text and "MY1" not in r.text
        make_rider(db, make_person(db, "Later"), "MY9", "Myntra")
        db.commit()
        assert client.get("/api/public/rider-stats").json()["riders_total"] == 3  # cached
    public.reset_cache()
