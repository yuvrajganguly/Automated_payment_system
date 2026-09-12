"""A photo of the vehicle going for repair, and one coming back (2026-09-12).

Two columns, not one, because they answer different arguments. The outgoing
picture is what was wrong — the evidence for the repair bill and for saying the
fault was not the rider's. The incoming one is whether the thing we asked for
was actually done, and what the next rider is being handed.

**Optional, by decision.** A photo makes the argument with the provider much
easier, but requiring one would mean a recruiter with a dying phone at a store
cannot log a fault at all — and a fault nobody logged is worse than one logged
without a picture. Most of this file is about that: every path works with no
photo, and the flags say so honestly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from payout.api import ratelimit
from payout.api.app import app
from payout.auth.passwords import hash_password
from payout.db import get_connection
from tests.conftest import make_ev

_ADMIN = ("admin@t.test", "Admin-pass-1", "admin")
_REC = ("rec@t.test", "Rec-pass-1", "recruiter")

# A one-pixel PNG: the smallest thing the content-type check will accept.
_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture
def client(db):
    with get_connection() as conn:
        for email, pw, role in (_ADMIN, _REC):
            conn.execute(
                "INSERT INTO users (email, password_hash, role) VALUES (?,?,?)",
                (email, hash_password(pw), role),
            )
        conn.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        yield c


def _login(client, who) -> dict:
    r = client.post("/api/auth/login", data={"username": who[0], "password": who[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


@pytest.fixture
def ev(db):
    make_ev(db, "EV-REPAIR")
    db.commit()
    return "EV-REPAIR"


def _send_for_repair(client, hdr, ev_id, reason="battery not charging"):
    r = client.post(
        "/api/evs/maintenance",
        json={"ev_id": ev_id, "from_date": "2026-09-12", "reason": reason},
        headers=hdr,
    )
    assert r.status_code == 201, r.text
    return r.json()


def _files(name="fault.png"):
    return {"file": (name, _PNG, "image/png")}


# ── the optional part ────────────────────────────────────────────────────────


def test_a_fault_can_be_logged_with_no_photo_at_all(client, ev):
    """The decision this feature turns on. A recruiter at a store with a dying
    phone still gets the vehicle off the road and the fault on the record."""
    rec = _login(client, _REC)
    row = _send_for_repair(client, rec, ev)
    assert row["has_out_photo"] is False and row["has_in_photo"] is False

    back = client.patch(f"/api/evs/maintenance/{row['id']}", json={}, headers=rec)
    assert back.status_code == 200, back.text
    assert back.json()["to_date"] is not None
    assert back.json()["has_in_photo"] is False


def test_no_photo_is_a_404_and_not_an_error(client, ev):
    rec = _login(client, _REC)
    row = _send_for_repair(client, rec, ev)
    assert client.get(f"/api/evs/maintenance/{row['id']}/photo", headers=rec).status_code == 404


# ── with photos ──────────────────────────────────────────────────────────────


def test_the_two_photos_are_kept_apart(client, ev):
    """The whole reason there are two columns: the picture of the fault must
    not be overwritten by the picture of the repaired vehicle, or there is no
    evidence left of what was wrong."""
    rec = _login(client, _REC)
    row = _send_for_repair(client, rec, ev)
    mid = row["id"]

    assert (
        client.post(
            f"/api/evs/maintenance/{mid}/photo?kind=out", files=_files("fault.png"), headers=rec
        ).status_code
        == 200
    )
    listed = client.get(f"/api/evs/maintenance?ev_id={ev}", headers=rec).json()[0]
    assert listed["has_out_photo"] is True and listed["has_in_photo"] is False

    client.patch(f"/api/evs/maintenance/{mid}", json={}, headers=rec)
    assert (
        client.post(
            f"/api/evs/maintenance/{mid}/photo?kind=in", files=_files("fixed.png"), headers=rec
        ).status_code
        == 200
    )
    listed = client.get(f"/api/evs/maintenance?ev_id={ev}", headers=rec).json()[0]
    assert listed["has_out_photo"] is True and listed["has_in_photo"] is True

    for kind in ("out", "in"):
        got = client.get(f"/api/evs/maintenance/{mid}/photo?kind={kind}", headers=rec)
        assert got.status_code == 200, kind
        assert got.content == _PNG


def test_the_office_can_see_what_it_is_being_billed_for(client, ev):
    rec = _login(client, _REC)
    row = _send_for_repair(client, rec, ev)
    client.post(f"/api/evs/maintenance/{row['id']}/photo", files=_files(), headers=rec)
    # kind defaults to "out" — the common case at the moment of sending.
    got = client.get(f"/api/evs/maintenance/{row['id']}/photo", headers=_login(client, _ADMIN))
    assert got.status_code == 200 and got.content == _PNG


def test_re_uploading_replaces_the_picture(client, ev):
    rec = _login(client, _REC)
    row = _send_for_repair(client, rec, ev)
    other = b"\x89PNG\r\n\x1a\n" + _PNG[8:-1] + b"\x83"
    client.post(f"/api/evs/maintenance/{row['id']}/photo", files=_files(), headers=rec)
    client.post(
        f"/api/evs/maintenance/{row['id']}/photo",
        files={"file": ("better.png", other, "image/png")},
        headers=rec,
    )
    got = client.get(f"/api/evs/maintenance/{row['id']}/photo", headers=rec)
    assert got.content == other


# ── refusals ─────────────────────────────────────────────────────────────────


def test_the_record_comes_before_the_picture(client, ev):
    """Same ordering as every other photo in the app: a failed upload on a
    hub's signal must cost the photo and not the report."""
    rec = _login(client, _REC)
    r = client.post("/api/evs/maintenance/9999/photo", files=_files(), headers=rec)
    assert r.status_code == 404


def test_a_pdf_is_not_a_photo_of_a_scooter(client, ev):
    rec = _login(client, _REC)
    row = _send_for_repair(client, rec, ev)
    r = client.post(
        f"/api/evs/maintenance/{row['id']}/photo",
        files={"file": ("invoice.pdf", b"%PDF-1.4", "application/pdf")},
        headers=rec,
    )
    assert r.status_code == 415


def test_an_empty_file_is_refused(client, ev):
    rec = _login(client, _REC)
    row = _send_for_repair(client, rec, ev)
    r = client.post(
        f"/api/evs/maintenance/{row['id']}/photo",
        files={"file": ("nothing.png", b"", "image/png")},
        headers=rec,
    )
    assert r.status_code == 400


def test_a_made_up_kind_is_refused(client, ev):
    """`kind` is interpolated into the column name, so it is checked against a
    fixed pair rather than trusted."""
    rec = _login(client, _REC)
    row = _send_for_repair(client, rec, ev)
    r = client.post(
        f"/api/evs/maintenance/{row['id']}/photo?kind=out_photo_key; DROP TABLE ev_units--",
        files=_files(),
        headers=rec,
    )
    assert r.status_code == 400
    assert (
        client.get(f"/api/evs/maintenance/{row['id']}/photo?kind=sideways", headers=rec).status_code
        == 400
    )
    # and the table is still there
    assert client.get("/api/evs", headers=rec).status_code == 200


def test_a_plain_user_cannot_upload(client, ev, db):
    db.execute(
        "INSERT INTO users (email, password_hash, role) VALUES (?,?,'user')",
        ("nobody@t.test", hash_password("Nobody-pass-1")),
    )
    db.commit()
    rec = _login(client, _REC)
    row = _send_for_repair(client, rec, ev)
    plain = _login(client, ("nobody@t.test", "Nobody-pass-1", "user"))
    r = client.post(f"/api/evs/maintenance/{row['id']}/photo", files=_files(), headers=plain)
    assert r.status_code == 403
