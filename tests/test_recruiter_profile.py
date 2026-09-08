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


# ── the EV came back: the recruiter's field report ──────────────────────────


def _closed_assignment(conn, *, returned_by: str) -> int:
    """A person holding an EV that has just come back, awaiting the deposit
    answer — the state the recruiter is standing in."""
    pid = conn.execute("INSERT INTO person_registry (display_name) VALUES ('R')").lastrowid
    conn.execute("INSERT INTO ev_models (provider, model_name, weekly_rate) VALUES ('P','M',70000)")
    mid = conn.execute("SELECT model_id FROM ev_models LIMIT 1").fetchone()[0]
    conn.execute(
        "INSERT INTO ev_units (ev_id, model_id, status) VALUES ('EV1',?,'returned')", (mid,)
    )
    conn.execute(
        "INSERT INTO ev_assignments (person_id, ev_id, handover_date, returned_date, "
        "  closeout_pending, returned_by) VALUES (?,'EV1','2026-08-01','2026-09-01',1,?)",
        (pid, returned_by),
    )
    return conn.execute("SELECT assignment_id FROM ev_assignments LIMIT 1").fetchone()[0]


def test_a_recruiter_reports_the_deposit_and_damage_without_moving_money(client):
    with get_connection() as conn:
        aid = _closed_assignment(conn, returned_by=_REC[0])
        conn.commit()
    h = _login(client, _REC)
    r = client.post(
        f"/api/evs/closeouts/{aid}/report",
        json={"sd_returned": False, "damage_charges": 850, "damage_note": "Cracked front panel"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["sd_returned"] is False
    assert r.json()["damage_charges"] == 850  # rupeeized out

    # A report is an observation. Nothing may have been posted to the ledger,
    # and the deposit must still be waiting for the office.
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM ev_closeouts").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT closeout_pending FROM ev_assignments WHERE assignment_id=?", (aid,)
            ).fetchone()[0]
            == 1
        )


def test_the_office_form_opens_on_what_the_recruiter_reported(client):
    with get_connection() as conn:
        aid = _closed_assignment(conn, returned_by=_REC[0])
        conn.commit()
    client.post(
        f"/api/evs/closeouts/{aid}/report",
        json={"sd_returned": False, "damage_charges": 850, "damage_note": "Cracked panel"},
        headers=_login(client, _REC),
    )
    pending = client.get("/api/evs/closeouts", headers=_login(client, _ADMIN)).json()
    row = next(p for p in pending if p["assignment_id"] == aid)
    assert row["report"]["reported_by"] == _REC[0]
    assert row["report"]["damage_note"] == "Cracked panel"
    # The admin confirms an answer rather than inventing one about a vehicle
    # they have not seen.
    assert row["suggested"]["damage_charges"] == 850
    assert row["suggested"]["sd_returned"] is False


def test_reporting_the_deposit_returned_zeroes_the_deposit_the_office_holds(client):
    with get_connection() as conn:
        aid = _closed_assignment(conn, returned_by=_REC[0])
        conn.commit()
    client.post(
        f"/api/evs/closeouts/{aid}/report",
        json={"sd_returned": True},
        headers=_login(client, _REC),
    )
    pending = client.get("/api/evs/closeouts", headers=_login(client, _ADMIN)).json()
    row = next(p for p in pending if p["assignment_id"] == aid)
    assert row["suggested"]["sd_returned"] is True
    assert row["suggested"]["sd_amount"] == 0


def test_the_deposit_cannot_go_back_and_damage_be_owed_at_the_same_time(client):
    with get_connection() as conn:
        aid = _closed_assignment(conn, returned_by=_REC[0])
        conn.commit()
    r = client.post(
        f"/api/evs/closeouts/{aid}/report",
        json={"sd_returned": True, "damage_charges": 500},
        headers=_login(client, _REC),
    )
    assert r.status_code == 400


def test_a_correction_replaces_the_report_rather_than_adding_a_second(client):
    with get_connection() as conn:
        aid = _closed_assignment(conn, returned_by=_REC[0])
        conn.commit()
    h = _login(client, _REC)
    client.post(
        f"/api/evs/closeouts/{aid}/report",
        json={"sd_returned": False, "damage_charges": 500},
        headers=h,
    )
    r = client.post(
        f"/api/evs/closeouts/{aid}/report",
        json={"sd_returned": False, "damage_charges": 900},
        headers=h,
    )
    assert r.json()["damage_charges"] == 900
    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM ev_closeout_reports").fetchone()[0] == 1


def test_a_report_is_refused_once_the_office_has_settled(client):
    """By then the number has already been charged; a later 'correction' would
    describe a settlement that never happened."""
    with get_connection() as conn:
        aid = _closed_assignment(conn, returned_by=_REC[0])
        conn.commit()
    settled = client.post(
        f"/api/evs/closeouts/{aid}",
        json={"sd_returned": False, "damage_charges": 0, "rent_charges": 0},
        headers=_login(client, _ADMIN),
    )
    assert settled.status_code == 200, settled.text
    r = client.post(
        f"/api/evs/closeouts/{aid}/report",
        json={"sd_returned": False, "damage_charges": 900},
        headers=_login(client, _REC),
    )
    assert r.status_code == 400
    assert "already settled" in r.json()["detail"]


def test_a_recruiter_still_cannot_settle_the_deposit(client):
    """The field report is an observation; applying it to arrears and dues is
    money, and the fence stays where it was."""
    with get_connection() as conn:
        aid = _closed_assignment(conn, returned_by=_REC[0])
        conn.commit()
    r = client.post(
        f"/api/evs/closeouts/{aid}",
        json={"sd_returned": False, "damage_charges": 900, "rent_charges": 0},
        headers=_login(client, _REC),
    )
    assert r.status_code == 403


def test_the_app_lists_the_vehicles_i_took_back_that_still_need_an_answer(client):
    with get_connection() as conn:
        _closed_assignment(conn, returned_by=_REC[0])
        conn.commit()
    mine = client.get("/api/evs/closeouts/mine", headers=_login(client, _REC)).json()
    assert [m["ev_id"] for m in mine] == ["EV1"]
    assert mine[0]["report"] is None  # not answered yet
    # A colleague who did not take it back is not prompted about it.
    assert client.get("/api/evs/closeouts/mine", headers=_login(client, _REC2)).json() == []


def test_the_damage_photo_hangs_off_a_report_that_already_exists(client):
    """Same ordering as everywhere else: the assessment saves first, the
    picture follows, so a failed upload costs the photo and not the number."""
    with get_connection() as conn:
        aid = _closed_assignment(conn, returned_by=_REC[0])
        conn.commit()
    h = _login(client, _REC)
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    files = {"file": ("damage.png", png, "image/png")}

    # No report yet — the photo has nothing to hang off.
    early = client.post(f"/api/evs/closeouts/{aid}/photo", files=files, headers=h)
    assert early.status_code == 404

    client.post(
        f"/api/evs/closeouts/{aid}/report",
        json={"sd_returned": False, "damage_charges": 850, "damage_note": "Cracked panel"},
        headers=h,
    )
    assert client.post(f"/api/evs/closeouts/{aid}/photo", files=files, headers=h).status_code == 200

    # The office can see what it is being asked to charge for.
    got = client.get(f"/api/evs/closeouts/{aid}/photo", headers=_login(client, _ADMIN))
    assert got.status_code == 200
    assert got.content == png
    pending = client.get("/api/evs/closeouts", headers=_login(client, _ADMIN)).json()
    assert next(p for p in pending if p["assignment_id"] == aid)["report"]["has_photo"] is True


def test_a_pdf_is_not_a_photo_of_a_scooter(client):
    with get_connection() as conn:
        aid = _closed_assignment(conn, returned_by=_REC[0])
        conn.commit()
    h = _login(client, _REC)
    client.post(f"/api/evs/closeouts/{aid}/report", json={"sd_returned": False}, headers=h)
    r = client.post(
        f"/api/evs/closeouts/{aid}/photo",
        files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
        headers=h,
    )
    assert r.status_code == 415
