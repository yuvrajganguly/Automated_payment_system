"""The recruiter layer (2026-09-03).

Recruiters are field staff: they onboard riders, set hubs and bank details,
upload KYC documents and run the fleet (add / assign / return / spare /
maintenance). They never see or touch money — they can only file a request
that an admin approves or rejects. Everything they do lands in the activity
log, which admins read per person.
"""

from __future__ import annotations

import io

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from payout.api import ratelimit  # noqa: E402
from payout.api.app import app  # noqa: E402
from payout.auth import hash_password  # noqa: E402
from payout.documents import reset_storage  # noqa: E402
from tests.conftest import make_ev, make_person  # noqa: E402

_CREATOR = ("owner@t.test", "Owner-pass-1", "creator")
_ADMIN = ("admin@t.test", "Admin-pass-1", "admin")
_RECRUITER = ("rec@t.test", "Recruit-pass-1", "recruiter")
_RECRUITER2 = ("rec2@t.test", "Recruit-pass-2", "recruiter")
_USER = ("user@t.test", "User-pass-1", "user")


@pytest.fixture
def client(db, tmp_path, monkeypatch):
    for email, pw, role in (_CREATOR, _ADMIN, _RECRUITER, _RECRUITER2, _USER):
        db.execute(
            "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
            (email, hash_password(pw), role),
        )
    db.commit()
    monkeypatch.setenv("PAYOUT_DOCS_DIR", str(tmp_path / "docs"))
    monkeypatch.delenv("PAYOUT_DOCS_S3_BUCKET", raising=False)
    reset_storage()
    ratelimit.reset()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    reset_storage()


def _login(client, who):
    email, pw, _ = who
    r = client.post("/api/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


# ── authorization matrix ─────────────────────────────────────────────────────


def test_recruiter_can_run_the_roster_and_fleet(db, client):
    h = _login(client, _RECRUITER)
    # add a rider (placeholder id), edit hub + bank, tag the real id
    r = client.post("/api/riders", json={"company": "Spencer's", "name": "Field Hire"}, headers=h)
    assert r.status_code == 201, r.text
    rid, pid = r.json()["rider_id"], r.json()["person_id"]
    r = client.patch(
        f"/api/riders/{rid}?company=Spencer's",
        json={"hub": "South City", "account_no": "12345678", "ifsc": "sbin0001"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["hub"] == "South City" and r.json()["ifsc"] == "SBIN0001"
    r = client.post(
        "/api/riders/rename-rider-id",
        json={"person_id": pid, "company": "Spencer's", "new_rider_id": "9000000001"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    # fleet: add + assign in one go, maintenance out and back, spare, return
    r = client.post(
        "/api/evs",
        json={"ev_id": "EV-REC-1", "provider": "Blive", "model": "Standard", "person_id": pid},
        headers=h,
    )
    assert r.status_code == 201, r.text
    r = client.post(
        "/api/evs/maintenance",
        json={"ev_id": "EV-REC-1", "from_date": "2026-09-01", "reason": "brake"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    mid = r.json()["id"]
    r = client.patch(f"/api/evs/maintenance/{mid}", json={"to_date": "2026-09-02"}, headers=h)
    assert r.status_code == 200, r.text
    r = client.post("/api/evs/to-spare", json={"ev_id": "EV-REC-1"}, headers=h)
    assert r.status_code == 200, r.text
    r = client.post("/api/evs/return", json={"ev_id": "EV-REC-1"}, headers=h)
    assert r.status_code == 200, r.text
    # roster and fleet reads
    assert client.get("/api/riders", headers=h).status_code == 200
    assert client.get("/api/evs", headers=h).status_code == 200
    assert client.get(f"/api/persons/{pid}", headers=h).status_code == 200


def test_recruiter_is_fenced_off_money_and_admin_routes(db, client):
    pid = make_person(db, "Someone")
    db.commit()
    h = _login(client, _RECRUITER)
    denied_get = [
        "/api/ledger/transactions",
        "/api/arrears",
        "/api/cod",
        "/api/payments/uploads",
        "/api/dashboard/story",
        "/api/inactive",
        "/api/ev-rent",
        "/api/corrections",
        "/api/cycles",
        "/api/creator/system/stats",
    ]
    for path in denied_get:
        r = client.get(path, headers=h)
        assert r.status_code in (403, 404, 405), f"{path} -> {r.status_code}"
        assert r.status_code != 200, path
    # money-side writes and admin-only roster surgery
    assert client.post("/api/riders/onboard-unknowns", json={}, headers=h).status_code == 403
    assert client.post("/api/persons/link", json={}, headers=h).status_code == 403
    assert (
        client.post(
            "/api/evs/amend-return", json={"ev_id": "X", "returned_date": "2026-01-01"}, headers=h
        ).status_code
        == 403
    )
    assert client.delete("/api/riders/R?company=Blitz", headers=h).status_code == 403
    assert client.post("/api/requests/1/approve", headers=h).status_code == 403
    assert (
        client.post(f"/api/persons/{pid}/arrears/write-off", json={}, headers=h).status_code == 403
    )


def test_recruiter_sees_standing_but_not_ledger_or_exports(db, client):
    """A recruiter sees the balance and arrears (so they don't request money
    that is already there) but not the transactions behind them, and cannot
    pull spreadsheets."""
    pid = make_person(db, "Rich Rider", balance=50_000, arrears=20_000)
    db.commit()
    h = _login(client, _RECRUITER)
    r = client.get(f"/api/persons/{pid}", headers=h).json()
    assert r["current_balance"] == 500.0 and r["arrears_outstanding"] == 200.0
    assert client.get(f"/api/ledger/{pid}", headers=h).status_code == 403
    assert client.post("/api/riders/export", json={"ids": []}, headers=h).status_code == 403
    assert client.post("/api/evs/export", json={"ids": []}, headers=h).status_code == 403
    r = client.get(f"/api/persons/{pid}", headers=_login(client, _ADMIN)).json()
    assert r["current_balance"] == 500.0 and r["arrears_outstanding"] == 200.0


def test_viewer_role_still_cannot_write(db, client):
    h = _login(client, _USER)
    assert (
        client.post("/api/riders", json={"company": "Blitz", "name": "X"}, headers=h).status_code
        == 403
    )
    assert client.post("/api/requests", json={}, headers=h).status_code == 403


def test_creator_can_create_recruiters(db, client):
    h = _login(client, _CREATOR)
    r = client.post(
        "/api/users",
        json={"email": "new.rec@t.test", "password": "Recruit-pass-9", "role": "recruiter"},
        headers=h,
    )
    assert r.status_code == 201, r.text
    assert r.json()["role"] == "recruiter"


# ── documents ────────────────────────────────────────────────────────────────


def _upload(client, h, pid, name="aadhaar.pdf", ctype="application/pdf", doc_type="aadhaar"):
    return client.post(
        f"/api/persons/{pid}/documents",
        files={"file": (name, io.BytesIO(b"%PDF-1.4 fake"), ctype)},
        data={"doc_type": doc_type, "notes": "front + back"},
        headers=h,
    )


def test_document_upload_list_download_delete(db, client, tmp_path):
    pid = make_person(db, "Doc Rider")
    db.commit()
    h = _login(client, _RECRUITER)
    r = _upload(client, h, pid)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert doc["doc_type"] == "aadhaar" and doc["uploaded_by"] == _RECRUITER[0]
    assert doc["size_bytes"] == len(b"%PDF-1.4 fake")
    # the bytes are on disk under the configured dir, under an opaque key
    files = list((tmp_path / "docs").rglob("*.pdf"))
    assert len(files) == 1 and "aadhaar" not in files[0].name

    r = client.get(f"/api/persons/{pid}/documents", headers=h)
    assert [d["id"] for d in r.json()] == [doc["id"]]

    r = client.get(f"/api/documents/{doc['id']}/download", headers=_login(client, _ADMIN))
    assert r.status_code == 200 and r.content == b"%PDF-1.4 fake"
    assert r.headers["content-type"].startswith("application/pdf")

    # recruiters edit but never delete — not even their own upload; admins do
    r = client.delete(f"/api/documents/{doc['id']}", headers=_login(client, _RECRUITER2))
    assert r.status_code == 403
    r = client.delete(f"/api/documents/{doc['id']}", headers=h)
    assert r.status_code == 403
    r = client.delete(f"/api/documents/{doc['id']}", headers=_login(client, _ADMIN))
    assert r.status_code == 200
    assert client.get(f"/api/persons/{pid}/documents", headers=h).json() == []
    assert list((tmp_path / "docs").rglob("*.pdf")) == []


def test_document_rejects_bad_type_and_unknown_kind(db, client):
    pid = make_person(db, "Doc Rider")
    db.commit()
    h = _login(client, _RECRUITER)
    r = _upload(client, h, pid, name="x.exe", ctype="application/octet-stream")
    assert r.status_code == 415
    r = _upload(client, h, pid, doc_type="passport")
    assert r.status_code == 400
    assert client.get("/api/documents/types", headers=h).json()["backend"] == "local"


# ── money requests ───────────────────────────────────────────────────────────


def test_money_request_flow(db, client):
    pid = make_person(db, "Cash Rider", balance=0)
    db.commit()
    rec = _login(client, _RECRUITER)
    r = client.post(
        "/api/requests",
        json={
            "person_id": pid,
            "direction": "credit",
            "amount": 500,
            "reason": "paid cash for helmet",
        },
        headers=rec,
    )
    assert r.status_code == 201, r.text
    req = r.json()
    assert req["status"] == "open" and req["amount"] == 500.0
    # recruiter can't approve their own ask
    assert client.post(f"/api/requests/{req['id']}/approve", headers=rec).status_code == 403
    # visible + counted for admins
    adm = _login(client, _ADMIN)
    assert client.get("/api/requests/summary", headers=adm).json() == {"open": 1}
    assert client.get(f"/api/requests?person_id={pid}", headers=adm).json()[0]["id"] == req["id"]
    # approve for a different amount → ledger adjustment for that amount
    r = client.post(
        f"/api/requests/{req['id']}/approve",
        json={"amount": 450, "note": "receipt shows 450"},
        headers=adm,
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved" and r.json()["applied_amount"] == 450.0
    assert r.json()["new_balance"] == 450.0
    bal = db.execute("SELECT current_balance FROM balances WHERE person_id=?", (pid,)).fetchone()[0]
    assert bal == 45_000
    txn = db.execute(
        "SELECT event_type, amount, remarks FROM transactions WHERE person_id=? ORDER BY id DESC",
        (pid,),
    ).fetchone()
    assert txn["event_type"] == "ADJUSTMENT" and txn["amount"] == 45_000
    assert "rec@t.test" in txn["remarks"] and "receipt shows 450" in txn["remarks"]
    # closed twice → 409
    assert client.post(f"/api/requests/{req['id']}/reject", headers=adm).status_code == 409
    assert client.get("/api/requests/summary", headers=adm).json() == {"open": 0}


def test_money_request_reject_and_debit(db, client):
    pid = make_person(db, "Debit Rider", balance=100_000)
    db.commit()
    rec = _login(client, _RECRUITER)
    adm = _login(client, _ADMIN)
    r = client.post(
        "/api/requests",
        json={"person_id": pid, "direction": "debit", "amount": 200, "reason": "lost charger"},
        headers=rec,
    )
    rid = r.json()["id"]
    r = client.post(f"/api/requests/{rid}/reject", json={"note": "already charged"}, headers=adm)
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert (
        db.execute("SELECT current_balance FROM balances WHERE person_id=?", (pid,)).fetchone()[0]
        == 100_000
    )
    # a second, approved debit
    r = client.post(
        "/api/requests",
        json={"person_id": pid, "direction": "debit", "amount": 200, "reason": "lost charger"},
        headers=rec,
    )
    r = client.post(f"/api/requests/{r.json()['id']}/approve", headers=adm)
    assert r.status_code == 200 and r.json()["new_balance"] == 800.0
    # recruiters list only their own requests
    other = _login(client, _RECRUITER2)
    assert client.get("/api/requests", headers=other).json() == []
    assert len(client.get("/api/requests", headers=rec).json()) == 2


def test_money_request_validation(db, client):
    pid = make_person(db, "X")
    db.commit()
    rec = _login(client, _RECRUITER)
    bad = [
        {"person_id": pid, "direction": "sideways", "amount": 10, "reason": "why"},
        {"person_id": pid, "direction": "credit", "amount": 0, "reason": "why"},
        {"person_id": 9999, "direction": "credit", "amount": 10, "reason": "why"},
        {"person_id": pid, "direction": "credit", "amount": 10, "reason": ""},
    ]
    for body in bad:
        assert client.post("/api/requests", json=body, headers=rec).status_code in (400, 404, 422)


# ── activity log ─────────────────────────────────────────────────────────────


def test_activity_is_recorded_and_scoped(db, client):
    rec = _login(client, _RECRUITER)
    r = client.post(
        "/api/riders", json={"company": "Blitz", "name": "Logged", "hub": "NTS"}, headers=rec
    )
    rid, pid = r.json()["rider_id"], r.json()["person_id"]
    client.patch(f"/api/riders/{rid}?company=Blitz", json={"hub": "Axis Hyper"}, headers=rec)
    make_ev(db, "EV-LOG")
    db.commit()
    client.post("/api/evs/assign", json={"ev_id": "EV-LOG", "person_id": pid}, headers=rec)
    client.post("/api/evs/return", json={"ev_id": "EV-LOG"}, headers=rec)

    adm = _login(client, _ADMIN)
    rows = client.get(f"/api/activity?email={_RECRUITER[0]}", headers=adm).json()
    actions = [x["action"] for x in rows]
    assert actions == ["ev.return", "ev.assign", "rider.update", "rider.create"]
    upd = next(x for x in rows if x["action"] == "rider.update")
    assert upd["details"]["changed"]["hub"] == ["NTS", "Axis Hyper"]
    assert upd["person_id"] == pid and upd["action_label"] == "Edited rider"
    # per-person view, and the people list
    assert len(client.get(f"/api/activity?person_id={pid}", headers=adm).json()) == 4
    people = client.get("/api/activity/people", headers=adm).json()
    assert people[0]["email"] == _RECRUITER[0] and people[0]["actions"] == 4
    # a recruiter sees only their own trail, whatever they ask for
    other = _login(client, _RECRUITER2)
    assert client.get(f"/api/activity?email={_RECRUITER[0]}", headers=other).json() == []
    mine = client.get("/api/activity", headers=rec).json()
    assert len(mine) == 4


def test_activity_survives_bad_details():
    from payout.domain.activity import record_activity

    class Conn:
        def __init__(self):
            self.params = None

        def execute(self, _sql, params):
            self.params = params

    c = Conn()
    record_activity(c, {"email": "a@b"}, "x.y", entity_type="t", entity_id=1, details={"s": {1, 2}})
    assert c.params[-1]  # serialised via default=str, never raised
