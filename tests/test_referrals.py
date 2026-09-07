"""Referrals: ₹1,000 to the referrer in two ₹500 instalments once the new
rider has worked four weeks — paid by the engine, shown in the preview."""

from __future__ import annotations

import io
from datetime import date

import pytest
from openpyxl import Workbook

from payout.domain.engine import process_cycle
from tests.conftest import make_person, make_rider


def _file(rows, headers=("rider_id", "net_pay")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def client(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    db.executemany(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        [
            ("rec@t.test", hash_password("Recruit-pass-1"), "recruiter"),
            ("boss@t.test", hash_password("Creator-pass-1"), "creator"),
        ],
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        yield c


def _hdr(client, email="rec@t.test", pw="Recruit-pass-1"):
    r = client.post("/api/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _balance(db, pid):
    row = db.execute("SELECT current_balance FROM balances WHERE person_id=?", (pid,)).fetchone()
    return int(row["current_balance"]) if row else 0


def _setup(db, client):
    """Arjun (referrer, Blitz) brings Bikash in on 1 June via the app."""
    rec = _hdr(client)
    arjun = make_person(db, "Arjun Das", balance=0)
    make_rider(db, arjun, "A1", "Blitz", "Arjun Das")
    db.commit()
    r = client.post(
        "/api/riders",
        json={
            "company": "Blitz",
            "name": "Bikash Roy",
            "rider_id": "B1",
            "referred_by_person_id": arjun,
        },
        headers=rec,
    )
    assert r.status_code in (200, 201), r.text
    assert r.json()["referred_by"] == "Arjun Das"
    bikash = r.json()["person_id"]
    db.execute("UPDATE rider_master SET created_at='2026-06-01 09:00:00' WHERE rider_id='B1'")
    db.commit()
    return rec, arjun, bikash


def test_referral_recorded_and_visible(db, client):
    rec, arjun, bikash = _setup(db, client)
    refs = client.get(f"/api/referrals?person_id={arjun}", headers=rec).json()
    assert len(refs) == 1 and refs[0]["status"] == "open" and refs[0]["new_name"] == "Bikash Roy"
    assert refs[0]["referrer_name"] == "Arjun Das" and refs[0]["created_by"] == "rec@t.test"
    assert client.get("/api/referrals?mine=1", headers=rec).json()[0]["id"] == refs[0]["id"]
    # One referrer per rider; no self-referral.
    r = client.post(
        "/api/referrals", json={"new_person_id": bikash, "referrer_person_id": arjun}, headers=rec
    )
    assert r.status_code == 409
    r = client.post(
        "/api/referrals", json={"new_person_id": arjun, "referrer_person_id": arjun}, headers=rec
    )
    assert r.status_code == 400
    rules = client.get("/api/referrals/rules", headers=rec).json()
    assert rules["bonus"] == 1000.0 and rules["installment_amount"] == 500.0
    assert rules["qualify_days"] == 28 and rules["installments"] == 2


def test_bonus_paid_in_two_installments_after_four_weeks(db, client):
    rec, arjun, bikash = _setup(db, client)
    both = lambda pay: _file([("A1", pay), ("B1", pay)])  # noqa: E731

    # Week 1 (1–7 June): Bikash's first payout. Too early — no bonus.
    r = process_cycle("Blitz", date(2026, 6, 1), date(2026, 6, 7), both(1000), commit=True)
    assert r.referral_bonuses == []
    a = next(x for x in r.pay_rows if x.person_id == arjun)
    assert a.referral_bonus == 0 and a.released == 100000

    # Cycle ending 28 June: 4 weeks not yet complete (needs 29 June). Still nothing.
    r = process_cycle("Blitz", date(2026, 6, 22), date(2026, 6, 28), both(1000), commit=True)
    assert r.referral_bonuses == []

    # Cycle ending 5 July: the month is reached → instalment 1 of 2 for Arjun.
    # A dry run shows it and writes nothing.
    r = process_cycle("Blitz", date(2026, 6, 29), date(2026, 7, 5), both(1000), commit=False)
    assert [(b["name"], b["installment"], b["amount"]) for b in r.referral_bonuses] == [
        ("Arjun Das", 1, 50000)
    ]
    assert db.execute("SELECT installments_paid FROM referrals").fetchone()[0] == 0
    r = process_cycle("Blitz", date(2026, 6, 29), date(2026, 7, 5), both(1000), commit=True)
    a = next(x for x in r.pay_rows if x.person_id == arjun)
    assert a.referral_bonus == 50000 and a.released == 150000
    ref = client.get(f"/api/referrals?person_id={bikash}", headers=rec).json()[0]
    assert ref["installments_paid"] == 1 and ref["status"] == "paying"
    assert ref["qualified_on"] == "2026-06-29" and ref["last_paid_cycle_end"] == "2026-07-05"
    # Re-running the same cycle (force) never pays the instalment twice.
    r = process_cycle(
        "Blitz", date(2026, 6, 29), date(2026, 7, 5), both(1000), commit=True, force=True
    )
    assert r.referral_bonuses == []

    # Next payout: instalment 2 of 2, then done.
    r = process_cycle("Blitz", date(2026, 7, 6), date(2026, 7, 12), both(1000), commit=True)
    a = next(x for x in r.pay_rows if x.person_id == arjun)
    assert a.referral_bonus == 50000 and a.released == 150000
    ref = client.get(f"/api/referrals?person_id={bikash}", headers=rec).json()[0]
    assert ref["installments_paid"] == 2 and ref["status"] == "paid"
    r = process_cycle("Blitz", date(2026, 7, 13), date(2026, 7, 19), both(1000), commit=True)
    assert r.referral_bonuses == []
    assert _balance(db, arjun) == 0
    adj = db.execute(
        "SELECT remarks FROM transactions WHERE person_id=? AND event_type='ADJUSTMENT' "
        "ORDER BY id",
        (arjun,),
    ).fetchall()
    assert [x["remarks"] for x in adj] == [
        "Referral bonus 1/2 — Bikash Roy completed four weeks",
        "Referral bonus 2/2 — Bikash Roy completed four weeks",
    ]


def test_no_bonus_when_the_new_rider_left_or_never_got_paid(db, client):
    rec, arjun, bikash = _setup(db, client)
    only_arjun = _file([("A1", 1000)])
    # Bikash never appears in a payout → no qualification, however long it has been.
    r = process_cycle("Blitz", date(2026, 7, 6), date(2026, 7, 12), only_arjun, commit=True)
    assert r.referral_bonuses == []
    # He gets paid once, then leaves before four weeks are up → nothing.
    process_cycle(
        "Blitz",
        date(2026, 7, 13),
        date(2026, 7, 19),
        _file([("A1", 1000), ("B1", 500)]),
        commit=True,
    )
    db.execute("UPDATE rider_master SET is_active=0 WHERE rider_id='B1'")
    db.commit()
    r = process_cycle("Blitz", date(2026, 7, 20), date(2026, 7, 26), only_arjun, commit=True)
    assert r.referral_bonuses == []
    # Admin voids it: stays void even if he comes back.
    boss = _hdr(client, "boss@t.test", "Creator-pass-1")
    ref = client.get(f"/api/referrals?person_id={bikash}", headers=rec).json()[0]
    assert client.post(f"/api/referrals/{ref['id']}/void", headers=rec).status_code == 403
    assert client.post(f"/api/referrals/{ref['id']}/void", headers=boss).json()["status"] == "void"
    db.execute("UPDATE rider_master SET is_active=1 WHERE rider_id='B1'")
    db.commit()
    r = process_cycle("Blitz", date(2026, 7, 27), date(2026, 8, 2), only_arjun, commit=True)
    assert r.referral_bonuses == []
