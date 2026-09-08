"""Regressions from the 2026-09-08 review.

Every test here failed before the fix it names. They cluster into three
subjects: renaming a company without corrupting anything, keeping identity and
bank numbers out of the places staff can read, and not letting the widened
admin role see or reach further than intended.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from payout.api import ratelimit
from payout.api.app import app
from payout.auth.passwords import hash_password
from payout.db import get_connection
from payout.db.references import rename_company

_CREATOR = ("owner@t.test", "Owner-pass-1", "creator")
_ADMIN = ("admin@t.test", "Admin-pass-1", "admin")
_REC = ("rec@t.test", "Rec-pass-1", "recruiter")


@pytest.fixture()
def client(db):  # noqa: ARG001 - the db fixture gives us a fresh database
    with get_connection() as conn:
        for email, pw, role in (_CREATOR, _ADMIN, _REC):
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
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _company(conn, name: str, **kw) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO companies (company_name, parser_type, rider_id_column, "
        "payout_column, payment_model) VALUES (?,?,?,?,?)",
        (name, "generic", "Rider id", "Pay", kw.get("payment_model", "payout_file")),
    )


# ── renaming a company ──────────────────────────────────────────────────────


def test_a_company_name_is_not_a_like_pattern(db):
    """'_' and '%' are LIKE wildcards. Matching the activity feed's
    ``rider_id@company`` suffix with LIKE meant renaming Big_Basket also
    rewrote BigXBasket's rows."""
    _company(db, "Big_Basket")
    _company(db, "BigXBasket")
    for entity in ("R1@Big_Basket", "R2@BigXBasket"):
        db.execute(
            "INSERT INTO activity_log (email, action, entity_type, entity_id) "
            "VALUES ('a@b','rider.create','rider',?)",
            (entity,),
        )
    rename_company(db, "Big_Basket", "Omega")
    ids = {r[0] for r in db.execute("SELECT entity_id FROM activity_log").fetchall()}
    assert ids == {"R1@Omega", "R2@BigXBasket"}


def test_the_rename_is_case_sensitive_on_both_backends(db):
    """SQLite's LIKE ignores case and PostgreSQL's does not, so the old query
    produced different data on the two engines — the bug class this project
    runs its suite twice to catch."""
    _company(db, "Alpha")
    for entity in ("R1@Alpha", "R999@alpha"):
        db.execute(
            "INSERT INTO activity_log (email, action, entity_type, entity_id) "
            "VALUES ('a@b','rider.create','rider',?)",
            (entity,),
        )
    rename_company(db, "Alpha", "Omega")
    ids = {r[0] for r in db.execute("SELECT entity_id FROM activity_log").fetchall()}
    assert ids == {"R1@Omega", "R999@alpha"}


def test_a_rider_id_that_ends_with_the_company_name_survives(db):
    _company(db, "Alpha")
    db.execute(
        "INSERT INTO activity_log (email, action, entity_type, entity_id) "
        "VALUES ('a@b','rider.create','rider','XAlpha@Alpha')"
    )
    rename_company(db, "Alpha", "Omega")
    assert db.execute("SELECT entity_id FROM activity_log").fetchone()[0] == "XAlpha@Omega"


def test_a_collision_refuses_loudly_instead_of_half_renaming(db):
    """Migrations run as one transaction, so an IntegrityError here would roll
    the whole batch back and the app would fail to start. Reachable in
    practice: deleting a company leaves its company_hubs rows behind."""
    _company(db, "Alpha")
    _company(db, "Omega")
    for co in ("Alpha", "Omega"):
        db.execute("INSERT INTO company_hubs (company, hub) VALUES (?, 'Salt Lake')", (co,))
    # delete_company drops the companies row and leaves the hubs behind, which
    # is what makes the name look free while its rows are still sitting there.
    db.execute("DELETE FROM companies WHERE company_name='Omega'")
    with pytest.raises(ValueError, match="company_hubs"):
        rename_company(db, "Alpha", "Omega")
    # Nothing moved.
    assert db.execute("SELECT COUNT(*) FROM company_hubs WHERE company='Alpha'").fetchone()[0] == 1


def test_renaming_twice_changes_nothing_the_second_time(db):
    _company(db, "Alpha")
    assert rename_company(db, "Alpha", "Omega") is True
    assert rename_company(db, "Alpha", "Omega") is False


# ── a deleted company must not rewrite history ──────────────────────────────


def test_deleting_a_company_does_not_flip_its_riders_to_idle(db):
    """The ledger outlives the companies row. An inner join meant deleting a
    company silently turned every rider it ever paid from working to idle —
    the number just quietly became wrong."""
    from payout.domain.worked import active_person_sql

    _company(db, "Omega")
    pid = db.execute("INSERT INTO person_registry (display_name) VALUES ('R')").lastrowid
    db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after) VALUES (?,'R1','Alpha',?,?,'PAYOUT',1000,1000)",
        (
            pid,
            (date.today() - timedelta(days=8)).isoformat(),
            (date.today() - timedelta(days=2)).isoformat(),
        ),
    )
    sql = f"SELECT ({active_person_sql('p.person_id')}) FROM person_registry p WHERE p.person_id=?"
    assert bool(db.execute(sql, (pid,)).fetchone()[0]) is True
    db.execute("DELETE FROM companies WHERE company_name='Alpha'")
    assert bool(db.execute(sql, (pid,)).fetchone()[0]) is True


# ── identity and bank numbers must not reach the logs ───────────────────────


def test_the_audit_log_never_stores_an_aadhaar_or_an_account_number(client):
    """The profile route keeps these out of the activity feed; the audit
    middleware used to keep a verbatim copy of the request one layer up — and
    that log is now readable by every admin, not just the creator."""
    client.patch(
        "/api/recruiters/me/profile",
        json={
            "full_name": "Samir",
            "aadhaar_no": "123456789012",
            "pan_no": "ABCDE1234F",
            "account_no": "004512339012",
            "ifsc": "HDFC0001234",
        },
        headers=_login(client, _REC),
    )
    rows = client.get("/api/creator/audit-log?limit=50", headers=_login(client, _ADMIN)).json()
    blob = json.dumps(rows)
    for secret in ("123456789012", "ABCDE1234F", "004512339012", "HDFC0001234"):
        assert secret not in blob, f"{secret} reached the audit log"
    assert "Samir" in blob, "the scrub should redact values, not swallow the whole body"


def test_a_riders_bank_details_do_not_reach_the_activity_feed(client):
    h = _login(client, _ADMIN)
    r = client.post(
        "/api/riders",
        json={
            "rider_id": "R1",
            "company": "Kaptan",
            "name": "Rider One",
            "account_no": "004512339012",
            "ifsc": "HDFC0001234",
        },
        headers=h,
    )
    assert r.status_code in (200, 201), r.text
    feed = json.dumps(client.get("/api/activity?limit=50", headers=h).json())
    assert "004512339012" not in feed
    assert "HDFC0001234" not in feed


# ── the widened admin role ──────────────────────────────────────────────────


def test_an_admin_never_learns_that_the_creator_tier_exists(client):
    """Three surfaces opened to admins in 2026-09. All three must mask the
    role the same way /api/users always has."""
    h = _login(client, _ADMIN)
    client.get("/api/auth/me", headers=_login(client, _CREATOR))  # a row in the audit log

    users = client.get("/api/users", headers=h).json()
    assert {r["email"]: r["role"] for r in users}[_CREATOR[0]] == "admin"

    profile = client.get(f"/api/recruiters/{_CREATOR[0]}/profile", headers=h).json()
    assert profile["role"] == "admin"

    audit = client.get("/api/creator/audit-log?limit=200", headers=h).json()
    assert "creator" not in {r.get("role") for r in audit}


def test_a_profile_that_was_never_saved_still_knows_whose_it_is(client):
    """recruiter_profiles is LEFT-joined, so reading p.email handed back a
    null identity for anyone who had not saved anything yet."""
    body = client.get("/api/recruiters/me/profile", headers=_login(client, _REC)).json()
    assert body["email"] == _REC[0]


def test_zone_obeys_the_same_rank_rule_as_every_other_write(client):
    """Zone is not cosmetic — the rider list falls back to it for hub-less
    riders — and it was the one write route in users.py with no rank check."""
    ha = _login(client, _ADMIN)
    assert (
        client.patch(f"/api/users/{_REC[0]}/zone", json={"zone": "North"}, headers=ha).status_code
        == 200
    )
    for target in (_ADMIN[0], _CREATOR[0]):
        r = client.patch(f"/api/users/{target}/zone", json={"zone": "South"}, headers=ha)
        assert r.status_code == 403, target
        assert "creator" not in r.text.lower()


# ── the odometer ────────────────────────────────────────────────────────────


def test_a_days_distance_can_never_be_negative(client):
    """Whatever a concurrent pair of saves does to the row, nothing may
    subtract from a fuel claim."""
    h = _login(client, _REC)
    day = date.today().isoformat()
    client.post("/api/recruiters/me/shift", json={"kind": "start", "km": 100}, headers=h)
    client.post("/api/recruiters/me/shift", json={"kind": "end", "km": 200}, headers=h)
    # Force the state a race could leave behind, then read it back through the API.
    with get_connection() as conn:
        conn.execute(
            "UPDATE recruiter_shifts SET start_km=500 WHERE email=? AND day=?", (_REC[0], day)
        )
        conn.commit()
    assert client.get("/api/recruiters/me/shift/today", headers=h).json()["distance_km"] == 0
    body = client.get("/api/recruiters/me/shifts?days=7", headers=h).json()
    assert body["total_km"] == 0
    months = client.get("/api/recruiters/me/shifts/monthly", headers=h).json()["months"]
    assert all(m["km"] >= 0 for m in months)
