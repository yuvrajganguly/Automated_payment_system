"""Dues below two days of the rider's own EV rent are not a visit (2026-09-12).

Rent is charged weekly and recovered out of a payout, and the two do not always
line up on the day — a leg starting mid-cycle, a handover dated a day either
side of when the vehicle really moved, a return booked late. The residue is a
rider showing a day or two of rent missed who has paid everything asked of
them. With the floor at zero the visit list filled with those and a rider
genuinely a week down queued behind sixty people owing a part-day.

The floor is two days of *their own* EV's rate, so it means "a tagging slip"
rather than an amount somebody picked: a Blue 370, a Regular 357, a Blive 360.
"""

from __future__ import annotations

import pytest

from payout.api.routes.app import dues_floor
from tests.conftest import assign, make_ev, make_person, make_rider


@pytest.fixture
def client(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("boss@t.test", hash_password("Creator-pass-1"), "creator"),
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        yield c


def _hdr(client):
    r = client.post(
        "/api/auth/login", data={"username": "boss@t.test", "password": "Creator-pass-1"}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_the_floor_is_two_days_of_that_model():
    assert dues_floor(129_500) == 37_000  # Blue, 1,295 a week  -> 370
    assert dues_floor(125_000) == 35_714  # Regular, 1,250      -> 357.14
    assert dues_floor(126_000) == 36_000  # Blive, 1,260        -> 360
    assert dues_floor(None) == 0  # no EV, no rent to mistag


def _rider(db, name, rider_id, ev_id, arrears):
    pid = make_person(db, name, arrears=arrears)
    make_rider(db, pid, rider_id, "Shadowfax", name)
    assign(db, pid, make_ev(db, ev_id, provider="Raft", model="Blue"), handover="2026-08-01")
    db.execute("UPDATE rider_master SET hub='Salt Lake' WHERE rider_id=?", (rider_id,))
    return pid


def test_two_days_of_rent_missed_is_not_a_visit(db, client):
    """370 is two days of a Blue exactly, so it is not enough; 371 is."""
    _rider(db, "Two Days", "SF-2D", "EV-2D", 37_000)
    _rider(db, "Just Over", "SF-OV", "EV-OV", 37_100)
    db.commit()
    t = client.get("/api/app/todo", headers=_hdr(client)).json()
    names = {i["name"] for s in t["stores"] for i in s["items"] if i["kind"] == "ev_dues"}
    assert names == {"Just Over"}
    assert t["counts"]["ev_dues_items"] == 1


def test_a_whole_week_still_shows(db, client):
    _rider(db, "Week Down", "SF-WK", "EV-WK", 129_500)
    db.commit()
    t = client.get("/api/app/todo", headers=_hdr(client)).json()
    dues = [i for s in t["stores"] for i in s["items"] if i["kind"] == "ev_dues"]
    assert [i["name"] for i in dues] == ["Week Down"]
    assert dues[0]["total_dues"] == 1295.0


def test_a_negative_balance_counts_towards_the_floor_too(db, client):
    """Dues are arrears plus an overdrawn balance; the floor sees the total,
    or a rider could sit just under it twice over and never appear."""
    pid = _rider(db, "Both Halves", "SF-BH", "EV-BH", 20_000)
    db.execute("INSERT INTO balances (person_id, current_balance) VALUES (?, -20000)", (pid,))
    db.commit()
    t = client.get("/api/app/todo", headers=_hdr(client)).json()
    dues = [i for s in t["stores"] for i in s["items"] if i["kind"] == "ev_dues"]
    assert [i["total_dues"] for i in dues] == [400.0]
