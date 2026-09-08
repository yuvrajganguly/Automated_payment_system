"""Recruiter profiles, odometer shifts, and who may read what.

The bank and identity numbers here are the most sensitive thing the system
stores about its own staff, so most of this file is about access rather than
arithmetic: a recruiter reads their own in full, an admin reads them on the
profile page, and nobody else gets them at all — not even masked-but-guessable.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from payout.api import ratelimit
from payout.api.app import app
from payout.auth.passwords import hash_password
from payout.db import get_connection

_CREATOR = ("owner@t.test", "Owner-pass-1", "creator")
_ADMIN = ("admin@t.test", "Admin-pass-1", "admin")
_REC = ("rec@t.test", "Rec-pass-1", "recruiter")
_REC2 = ("rec2@t.test", "Rec2-pass-1", "recruiter")


@pytest.fixture()
def client(db):  # noqa: ARG001 - the db fixture gives us a fresh database
    with get_connection() as conn:
        for email, pw, role in (_CREATOR, _ADMIN, _REC, _REC2):
            conn.execute(
                "INSERT INTO users (email, password_hash, role) VALUES (?,?,?)",
                (email, hash_password(pw), role),
            )
        conn.commit()
    # Every test in this file signs in several accounts; without this the
    # login bucket trips partway through the module and the failures look
    # like auth bugs.
    ratelimit.reset()
    with TestClient(app) as c:
        yield c


def _login(client, who) -> dict:
    r = client.post("/api/auth/login", data={"username": who[0], "password": who[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── profile ─────────────────────────────────────────────────────────────────


def test_recruiter_saves_and_reads_their_own_profile(client):
    h = _login(client, _REC)
    r = client.patch(
        "/api/recruiters/me/profile",
        json={
            "full_name": "Samir Purkait",
            "account_no": "004512339012",
            "ifsc": "HDFC0001234",
            "bank_name": "HDFC",
            "aadhaar_no": "1234 5678 9012",
            "pan_no": "abcde1234f",
        },
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    # Their own profile comes back whole, and normalised on the way in.
    assert body["masked"] is False
    assert body["aadhaar_no"] == "123456789012"
    assert body["pan_no"] == "ABCDE1234F"
    assert body["account_no"] == "004512339012"
    assert (
        client.get("/api/recruiters/me/profile", headers=h).json()["full_name"] == "Samir Purkait"
    )


def test_a_partial_save_leaves_the_other_fields_alone(client):
    """The app saves one section at a time on a bad signal, so an omitted
    field must not be read as 'clear this'."""
    h = _login(client, _REC)
    client.patch(
        "/api/recruiters/me/profile", json={"full_name": "A", "pan_no": "ABCDE1234F"}, headers=h
    )
    client.patch("/api/recruiters/me/profile", json={"bank_name": "SBI"}, headers=h)
    body = client.get("/api/recruiters/me/profile", headers=h).json()
    assert (body["full_name"], body["pan_no"], body["bank_name"]) == ("A", "ABCDE1234F", "SBI")


def test_bad_identity_and_bank_values_are_refused(client):
    h = _login(client, _REC)
    for payload in (
        {"aadhaar_no": "123"},
        {"pan_no": "NOTAPAN"},
        {"ifsc": "hdfc1234"},
        {"account_no": "12ab34"},
    ):
        assert (
            client.patch("/api/recruiters/me/profile", json=payload, headers=h).status_code == 400
        )


def test_an_admin_sees_the_numbers_and_a_colleague_sees_nothing(client):
    client.patch(
        "/api/recruiters/me/profile",
        json={"account_no": "004512339012", "aadhaar_no": "123456789012"},
        headers=_login(client, _REC),
    )
    admin = client.get(f"/api/recruiters/{_REC[0]}/profile", headers=_login(client, _ADMIN)).json()
    assert admin["masked"] is False
    assert admin["account_no"] == "004512339012"

    # Another recruiter is refused outright — not shown a masked version.
    r = client.get(f"/api/recruiters/{_REC[0]}/profile", headers=_login(client, _REC2))
    assert r.status_code == 403


def test_the_activity_feed_records_the_change_but_never_the_numbers(client):
    """An Aadhaar number has no business in a feed every admin can read."""
    client.patch(
        "/api/recruiters/me/profile",
        json={"aadhaar_no": "123456789012", "account_no": "004512339012"},
        headers=_login(client, _REC),
    )
    rows = client.get("/api/activity?limit=50", headers=_login(client, _ADMIN)).json()
    feed = [r for r in rows if r["action"] == "profile.update"]
    assert feed, "the profile edit should appear in the feed"
    blob = str(feed[0])
    assert "aadhaar_no" in blob  # the field name is fine
    assert "123456789012" not in blob  # the value is not
    assert "004512339012" not in blob


# ── shifts ──────────────────────────────────────────────────────────────────


def test_a_days_distance_is_end_minus_start(client):
    h = _login(client, _REC)
    day = date.today().isoformat()
    assert (
        client.post(
            "/api/recruiters/me/shift", json={"kind": "start", "km": 12_340}, headers=h
        ).status_code
        == 200
    )
    r = client.post("/api/recruiters/me/shift", json={"kind": "end", "km": 12_398}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["distance_km"] == 58
    assert r.json()["complete"] is True
    today = client.get("/api/recruiters/me/shift/today", headers=h).json()
    assert (today["day"], today["distance_km"]) == (day, 58)


def test_a_closing_reading_below_the_opening_one_is_refused(client):
    h = _login(client, _REC)
    client.post("/api/recruiters/me/shift", json={"kind": "start", "km": 12_340}, headers=h)
    r = client.post("/api/recruiters/me/shift", json={"kind": "end", "km": 12_000}, headers=h)
    assert r.status_code == 400
    assert "below" in r.json()["detail"]


def test_closing_before_opening_is_refused(client):
    h = _login(client, _REC)
    r = client.post("/api/recruiters/me/shift", json={"kind": "end", "km": 12_000}, headers=h)
    assert r.status_code == 400


def test_an_odometer_that_went_backwards_warns_but_still_saves(client):
    """Vehicles get swapped and serviced. Blocking the shift because the
    reading dropped would leave a recruiter unable to record their day."""
    h = _login(client, _REC)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    client.post(
        "/api/recruiters/me/shift",
        json={"kind": "start", "km": 40_000, "day": yesterday},
        headers=h,
    )
    client.post(
        "/api/recruiters/me/shift", json={"kind": "end", "km": 40_050, "day": yesterday}, headers=h
    )
    r = client.post("/api/recruiters/me/shift", json={"kind": "start", "km": 900}, headers=h)
    assert r.status_code == 200
    assert r.json()["warnings"], "a lower reading than yesterday's close should warn"
    assert r.json()["start_km"] == 900


def test_resaving_a_reading_corrects_it_rather_than_adding_a_row(client):
    h = _login(client, _REC)
    client.post("/api/recruiters/me/shift", json={"kind": "start", "km": 100}, headers=h)
    client.post("/api/recruiters/me/shift", json={"kind": "start", "km": 120}, headers=h)
    client.post("/api/recruiters/me/shift", json={"kind": "end", "km": 200}, headers=h)
    body = client.get("/api/recruiters/me/shifts?days=7", headers=h).json()
    assert len(body["days"]) == 1
    assert body["days"][0]["start_km"] == 120
    assert body["total_km"] == 80


def test_an_open_day_contributes_nothing_to_the_month(client):
    """A day nobody closed must not quietly shorten the fuel claim — it is
    reported as open instead of counted as zero."""
    h = _login(client, _REC)
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    client.post(
        "/api/recruiters/me/shift", json={"kind": "start", "km": 10, "day": yesterday}, headers=h
    )
    client.post(
        "/api/recruiters/me/shift", json={"kind": "end", "km": 60, "day": yesterday}, headers=h
    )
    client.post(
        "/api/recruiters/me/shift", json={"kind": "start", "km": 60}, headers=h
    )  # left open
    months = client.get("/api/recruiters/me/shifts/monthly", headers=h).json()["months"]
    this_month = next(m for m in months if m["month"] == date.today().strftime("%Y-%m"))
    assert this_month["km"] == 50
    assert this_month["days_recorded"] == 1
    assert this_month["days_open"] >= 1


def test_a_recruiter_cannot_read_a_colleagues_odometer(client):
    h = _login(client, _REC)
    client.post("/api/recruiters/me/shift", json={"kind": "start", "km": 10}, headers=h)
    assert (
        client.get(f"/api/recruiters/{_REC[0]}/shifts", headers=_login(client, _REC2)).status_code
        == 403
    )
    assert (
        client.get(f"/api/recruiters/{_REC[0]}/shifts", headers=_login(client, _ADMIN)).status_code
        == 200
    )


def test_a_future_day_is_refused(client):
    h = _login(client, _REC)
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    r = client.post(
        "/api/recruiters/me/shift", json={"kind": "start", "km": 10, "day": tomorrow}, headers=h
    )
    assert r.status_code == 400


# ── analytics ───────────────────────────────────────────────────────────────


def test_the_board_is_admin_only(client):
    assert client.get("/api/recruiters", headers=_login(client, _REC)).status_code == 403
    assert client.get("/api/recruiters", headers=_login(client, _ADMIN)).status_code == 200
