"""Whose name the bank account is in (migration 0031).

Riders are often paid into a relative's account, and a payout file whose
beneficiary name disagrees with the bank's is bounced. ``account_name`` records
that name — but only when it differs.

The rule under test throughout: **blank means "the same as the rider"**, stored
as NULL. Storing a copy of the rider's own name instead would look identical on
screen and be wrong in two ways — it destroys the distinction between "nobody
said" and "somebody said it is in his wife's name", and it goes stale the first
time a spelling is corrected.
"""

from __future__ import annotations

import pytest

from tests.conftest import make_person, make_rider


@pytest.fixture
def client(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("adm@t.test", hash_password("Admin-pass-1"), "admin"),
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        assert (
            c.post(
                "/api/auth/login", data={"username": "adm@t.test", "password": "Admin-pass-1"}
            ).status_code
            == 200
        )
        yield c


def _holder(db, rider_id, company):
    row = db.execute(
        "SELECT account_name FROM rider_master WHERE rider_id=? AND company=?",
        (rider_id, company),
    ).fetchone()
    return row["account_name"]


def test_blank_holder_is_stored_as_null(db, client):
    r = client.post(
        "/api/riders",
        json={"company": "Kaptan", "name": "Somnath Sardar", "rider_id": "K1"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["account_name"] is None
    assert _holder(db, "K1", "Kaptan") is None


def test_whitespace_only_holder_is_also_null(db, client):
    """A recruiter who taps the field and leaves a space has said nothing."""
    r = client.post(
        "/api/riders",
        json={
            "company": "Kaptan",
            "name": "Somnath Sardar",
            "rider_id": "K2",
            "account_name": "   ",
        },
    )
    assert r.status_code == 201, r.text
    assert _holder(db, "K2", "Kaptan") is None


def test_a_different_holder_is_kept(db, client):
    r = client.post(
        "/api/riders",
        json={
            "company": "Kaptan",
            "name": "Somnath Sardar",
            "rider_id": "K3",
            "account_no": "911022334455",
            "ifsc": "HDFC0000123",
            "account_name": "Rekha Sardar",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["account_name"] == "Rekha Sardar"
    assert _holder(db, "K3", "Kaptan") == "Rekha Sardar"


def test_patch_sets_and_clears_the_holder(db, client):
    client.post("/api/riders", json={"company": "Kaptan", "name": "Jeet Ghosh", "rider_id": "K4"})
    r = client.patch("/api/riders/K4?company=Kaptan", json={"account_name": "Bina Ghosh"})
    assert r.status_code == 200, r.text
    assert _holder(db, "K4", "Kaptan") == "Bina Ghosh"
    # An empty string is the only way back to "same as the rider".
    r = client.patch("/api/riders/K4?company=Kaptan", json={"account_name": ""})
    assert r.status_code == 200, r.text
    assert _holder(db, "K4", "Kaptan") is None


def test_holder_is_not_touched_when_the_patch_omits_it(db, client):
    client.post(
        "/api/riders",
        json={
            "company": "Kaptan",
            "name": "Jeet Ghosh",
            "rider_id": "K5",
            "account_name": "Bina Ghosh",
        },
    )
    r = client.patch("/api/riders/K5?company=Kaptan", json={"hub": "Salt Lake"})
    assert r.status_code == 200, r.text
    assert _holder(db, "K5", "Kaptan") == "Bina Ghosh"


def test_renaming_the_rider_leaves_the_holder_alone(db, client):
    """The point of the NULL default: a spelling fix must not silently
    rewrite whose account it is, in either direction."""
    client.post(
        "/api/riders",
        json={
            "company": "Kaptan",
            "name": "Somnath Sardr",
            "rider_id": "K6",
            "account_name": "Rekha Sardar",
        },
    )
    r = client.patch("/api/riders/K6?company=Kaptan", json={"name": "Somnath Sardar"})
    assert r.status_code == 200, r.text
    assert _holder(db, "K6", "Kaptan") == "Rekha Sardar"


# ── adding an existing rider to a second company ─────────────────────────────


def test_second_company_copies_the_holder_with_the_account(db, client):
    """Bank details are the person's, not the company's, so the holder name
    travels with the account number when a second id is added."""
    first = client.post(
        "/api/riders",
        json={
            "company": "Kaptan",
            "name": "Somnath Sardar",
            "rider_id": "K7",
            "account_no": "911022334455",
            "ifsc": "HDFC0000123",
            "account_name": "Rekha Sardar",
            "mob_no": "9876543210",
        },
    )
    assert first.status_code == 201, first.text
    pid = first.json()["person_id"]

    second = client.post(
        "/api/riders",
        json={"company": "Jiffy", "name": "Somnath Sardar", "rider_id": "J7", "person_id": pid},
    )
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["person_id"] == pid, "the second id must attach, not mint a new person"
    assert body["account_name"] == "Rekha Sardar"
    assert "account_name" in (body["copied_from"] or {})["fields"]
    assert _holder(db, "J7", "Jiffy") == "Rekha Sardar"


def test_second_company_does_not_invent_a_holder(db, client):
    """A NULL on the first row means "the rider's own name". Copying it across
    as a NULL is right; copying the rider's name across is not."""
    first = client.post(
        "/api/riders",
        json={
            "company": "Kaptan",
            "name": "Jeet Ghosh",
            "rider_id": "K8",
            "account_no": "911099887766",
            "ifsc": "HDFC0000123",
        },
    )
    pid = first.json()["person_id"]
    second = client.post(
        "/api/riders",
        json={"company": "Jiffy", "name": "Jeet Ghosh", "rider_id": "J8", "person_id": pid},
    )
    assert second.status_code == 201, second.text
    assert _holder(db, "J8", "Jiffy") is None
    # The account itself still came across.
    assert second.json()["account_no"] == "911099887766"


def test_second_company_keeps_an_explicit_holder_over_the_copy(db, client):
    """Two ids can legitimately be paid into different accounts. What the
    recruiter typed wins over what the other row had."""
    first = client.post(
        "/api/riders",
        json={
            "company": "Kaptan",
            "name": "Somnath Sardar",
            "rider_id": "K9",
            "account_no": "911022334455",
            "ifsc": "HDFC0000123",
            "account_name": "Rekha Sardar",
        },
    )
    pid = first.json()["person_id"]
    second = client.post(
        "/api/riders",
        json={
            "company": "Jiffy",
            "name": "Somnath Sardar",
            "rider_id": "J9",
            "person_id": pid,
            "account_no": "911055667788",
            "ifsc": "ICIC0000456",
            "account_name": "Somnath Sardar Snr",
        },
    )
    assert second.status_code == 201, second.text
    assert _holder(db, "J9", "Jiffy") == "Somnath Sardar Snr"


def test_second_company_skips_the_duplicate_name_block(db, client):
    """Without person_id the same name at the same company is a 409. With it,
    attaching is the stated intent — this is what the app's new action relies
    on, and it must keep working."""
    first = client.post(
        "/api/riders", json={"company": "Kaptan", "name": "Amit Naskar", "rider_id": "KA"}
    )
    pid = first.json()["person_id"]
    blocked = client.post(
        "/api/riders", json={"company": "Kaptan", "name": "Amit Naskar", "rider_id": "KB"}
    )
    assert blocked.status_code == 409
    ok = client.post(
        "/api/riders",
        json={"company": "Kaptan", "name": "Amit Naskar", "rider_id": "KC", "person_id": pid},
    )
    assert ok.status_code == 201, ok.text
    assert ok.json()["person_id"] == pid


def test_holder_survives_the_migration_on_an_existing_row(db):
    """Migration 0031 adds the column; nothing is backfilled, because a copy
    of every rider's own name is exactly what the NULL is there to avoid."""
    pid = make_person(db, "Legacy Rider")
    make_rider(db, pid, "L1", "Kaptan", "Legacy Rider")
    db.commit()
    assert _holder(db, "L1", "Kaptan") is None
