"""Onboarding fixes (2026-09-02):

1. A new rider with the SAME NAME as an existing person must get a NEW
   person — never a silent merge (two different Amit Naskars are two people).
   Linking is explicit: pass person_id / use the onboarding "link" action.
2. Myntra payout files call the name column "Worker Name" — the parser must
   pick it up for the onboarding panel.
3. EVs can be assigned by person_id directly, not only (rider_id, company).
"""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from tests.conftest import make_ev, make_person, make_rider


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


# ── 1. no name-only auto-link ────────────────────────────────────────────────


def test_same_name_creates_a_new_person(db, client):
    existing = make_person(db, "Amit Naskar")
    make_rider(db, existing, "J1", "Jiffy", "Amit Naskar")
    db.commit()
    r = client.post(
        "/api/riders/onboard-unknowns",
        json={
            "company": "Blitz",
            "rows": [{"rider_id": "B9", "action": "create", "name": "Amit Naskar"}],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["committed"] and body["summary"]["created"] == 1
    new_pid = body["created"][0]["person_id"]
    assert new_pid != existing, "same name must NOT merge into the existing person"
    # Two distinct persons with the same display name now exist.
    n = db.execute(
        "SELECT COUNT(*) FROM person_registry WHERE display_name='Amit Naskar'"
    ).fetchone()[0]
    assert n == 2


def test_explicit_link_still_works(db, client):
    existing = make_person(db, "Same Guy")
    make_rider(db, existing, "J2", "Jiffy", "Same Guy")
    db.commit()
    r = client.post(
        "/api/riders/onboard-unknowns",
        json={
            "company": "Blitz",
            "rows": [{"rider_id": "B10", "action": "link", "link_to_person_id": existing}],
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["linked"] == [{"rider_id": "B10", "person_id": existing}]


def test_shared_account_is_still_a_conflict(db, client):
    existing = make_person(db, "Owner")
    make_rider(db, existing, "J3", "Jiffy", "Owner")
    db.execute("UPDATE rider_master SET account_no='111222333' WHERE rider_id='J3'")
    db.commit()
    r = client.post(
        "/api/riders/onboard-unknowns",
        json={
            "company": "Blitz",
            "rows": [
                {
                    "rider_id": "B11",
                    "action": "create",
                    "name": "Somebody Else",
                    "account_no": "111222333",
                }
            ],
        },
    )
    body = r.json()
    assert body["committed"] is False and body["summary"]["errors"] == 1


# ── 2. Myntra "Worker Name" header ───────────────────────────────────────────


def test_parser_reads_worker_name_column(db):
    from payout.domain.engine import process_cycle

    wb = Workbook()
    ws = wb.active
    ws.append(["rider_id", "Worker Name", "net_pay"])
    ws.append(["NEW1", "Fresh Rider", 1000])
    buf = io.BytesIO()
    wb.save(buf)
    r = process_cycle("Blitz", "2026-06-01", "2026-06-07", buf.getvalue(), commit=False)
    unk = [u for u in r.unknown_riders if u["rider_id"] == "NEW1"]
    assert unk and unk[0].get("name") == "Fresh Rider", (
        "'Worker Name' header must feed the onboarding panel's name"
    )


# ── 3. assign EV by person_id ────────────────────────────────────────────────


def test_assign_ev_by_person_id(db, client):
    pid = make_person(db, "Direct Assign")
    make_ev(db, "EV-P1", provider="Raft", model="Regular")
    db.commit()
    r = client.post("/api/evs/assign", json={"ev_id": "EV-P1", "person_id": pid})
    assert r.status_code == 200, r.text
    assert r.json()["person_id"] == pid
    open_a = db.execute(
        "SELECT person_id FROM ev_assignments WHERE ev_id='EV-P1' AND returned_date IS NULL"
    ).fetchone()
    assert open_a["person_id"] == pid
    # Unknown person -> 404; neither selector -> 400.
    make_ev(db, "EV-P2", provider="Raft", model="Regular")
    db.commit()
    assert (
        client.post("/api/evs/assign", json={"ev_id": "EV-P2", "person_id": 999999}).status_code
        == 404
    )
    assert client.post("/api/evs/assign", json={"ev_id": "EV-P2"}).status_code == 400


# ── 4. delete a rider id ─────────────────────────────────────────────────────


def test_delete_rider_id_reanchors_deduction(db, client):
    pid = make_person(db, "TwoIds")
    make_rider(db, pid, "R1", "Blitz", "TwoIds")
    make_rider(db, pid, "R2", "Myntra", "TwoIds")
    db.execute(
        "UPDATE person_registry SET deduction_rider_id='R1', deduction_company='Blitz' "
        "WHERE person_id=?",
        (pid,),
    )
    db.commit()

    r = client.delete("/api/riders/R1?company=Blitz")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["deleted"] == {"rider_id": "R1", "company": "Blitz"}
    assert body["remaining_rider_ids"] == 1
    assert body["deduction_moved_to"] == {"rider_id": "R2", "company": "Myntra"}
    assert (
        db.execute(
            "SELECT COUNT(*) FROM rider_master WHERE rider_id='R1' AND company='Blitz'"
        ).fetchone()[0]
        == 0
    )
    anchor = db.execute(
        "SELECT deduction_rider_id, deduction_company FROM person_registry WHERE person_id=?",
        (pid,),
    ).fetchone()
    assert (anchor["deduction_rider_id"], anchor["deduction_company"]) == ("R2", "Myntra")

    # deleting the last id clears the anchor; the person survives
    r2 = client.delete("/api/riders/R2?company=Myntra")
    assert r2.status_code == 200
    assert r2.json()["remaining_rider_ids"] == 0
    assert r2.json()["deduction_moved_to"] is None
    anchor = db.execute(
        "SELECT deduction_rider_id, deduction_company FROM person_registry WHERE person_id=?",
        (pid,),
    ).fetchone()
    assert anchor["deduction_rider_id"] is None and anchor["deduction_company"] is None
    assert (
        db.execute("SELECT COUNT(*) FROM person_registry WHERE person_id=?", (pid,)).fetchone()[0]
        == 1
    )


def test_delete_rider_id_unknown_404(db, client):
    assert client.delete("/api/riders/NOPE?company=Blitz").status_code == 404


def test_duplicate_name_can_be_added_anyway_but_not_duplicate_account(db, client):
    """Two different 'Amit Naskar's at one company: the warning stands, the
    operator can push through by name — never by bank account."""
    r = client.post(
        "/api/riders",
        json={"company": "Blitz", "name": "Amit Naskar", "account_no": "111"},
    )
    assert r.status_code == 201, r.text
    first = r.json()["person_id"]
    dup = {"company": "Blitz", "name": "amit naskar", "account_no": "222"}
    r = client.post("/api/riders", json=dup)
    assert r.status_code == 409 and "add anyway" in r.text
    r = client.post("/api/riders", json={**dup, "allow_duplicate_name": True})
    assert r.status_code == 201, r.text
    assert r.json()["person_id"] != first  # a separate person, not a merge
    # Same bank account is still refused even with the bypass.
    r = client.post(
        "/api/riders",
        json={
            "company": "Blitz",
            "name": "Amit Naskar",
            "account_no": "111",
            "allow_duplicate_name": True,
        },
    )
    assert r.status_code == 409


def test_second_rider_id_copies_bank_and_phone_from_the_person(db, client):
    """Adding a rider id at another company to a known person carries their
    account, IFSC and phone across when left blank — and says so. A value
    typed on the form wins over the copy. Phone is stored at onboarding."""
    r = client.post(
        "/api/riders",
        json={
            "company": "Blitz",
            "name": "Copy Rider",
            "account_no": "5550001",
            "ifsc": "HDFC0000123",
            "mob_no": "98765 43210",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["mob_no"] == "98765 43210"  # used to be dropped on the floor
    pid = r.json()["person_id"]
    r = client.post(
        "/api/riders",
        json={"company": "Myntra", "name": "Copy Rider", "person_id": pid, "rider_id": "MY-COPY"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["account_no"], body["ifsc"], body["mob_no"]) == (
        "5550001",
        "HDFC0000123",
        "98765 43210",
    )
    assert body["copied_from"]["fields"] == ["account_no", "ifsc", "mob_no"]
    assert body["copied_from"]["from"].endswith("@Blitz")
    row = db.execute(
        "SELECT account_no, ifsc, mob_no FROM rider_master WHERE rider_id='MY-COPY'"
    ).fetchone()
    assert (row["account_no"], row["ifsc"], row["mob_no"]) == (
        "5550001",
        "HDFC0000123",
        "98765 43210",
    )
    # A different account given explicitly is kept, only the blanks are copied.
    r = client.post(
        "/api/riders",
        json={
            "company": "Dealshare",
            "name": "Copy Rider",
            "person_id": pid,
            "rider_id": "DS-COPY",
            "account_no": "7770002",
        },
    )
    assert r.status_code == 201, r.text
    assert r.json()["account_no"] == "7770002"
    assert r.json()["copied_from"]["fields"] == ["ifsc", "mob_no"]
