"""Admin → Companies: how each company pays, and the two file-less flows.

* payout_file — unchanged: upload the file.
* per_order   — the office types order counts; payout = orders × rate, then
                the normal cycle (rent deducted, rest released).
* direct      — they pay riders themselves; the cycle route refuses.
"""

from __future__ import annotations

import json

import pytest

from tests.conftest import assign, make_ev, make_person, make_rider

WEEK_R = 1250.0  # Raft Regular weekly rate in rupees


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


def test_list_shows_model_rate_and_rider_counts(db, client):
    pid = make_person(db, "SF Rider")
    make_rider(db, pid, "SF-1", "Shadowfax", "SF Rider")
    db.commit()
    rows = {c["company_name"]: c for c in client.get("/api/companies").json()}
    sf = rows["Shadowfax"]
    assert sf["payment_model"] == "per_order"
    assert sf["per_order_rate"] == 15.0  # rupees on the wire
    assert (sf["active_riders"], sf["rider_ids"]) == (1, 1)
    assert rows["Zomato"]["payment_model"] == "direct"
    assert rows["Spencer's"]["cadence"] == "slots"
    assert rows["Blitz"]["payment_model"] == "payout_file"


def test_create_and_update_company(db, client):
    # A payout-file company needs its columns.
    r = client.post(
        "/api/companies", json={"company_name": "Nykaa2", "payment_model": "payout_file"}
    )
    assert r.status_code == 400
    r = client.post(
        "/api/companies",
        json={
            "company_name": "Swiggy",
            "payment_model": "payout_file",
            "cadence": "monthly",
            "rider_id_column": "DE ID",
            "payout_column": "Net Pay",
            "orders_column": "Orders",
            "notes": "monthly statement",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["parser_type"] == "swiggy" and body["cadence"] == "monthly"
    assert body["is_active"] is True and body["per_order_rate"] is None
    # Duplicate (any case) is refused; a per-order company needs a rate.
    assert client.post("/api/companies", json={"company_name": "swiggy"}).status_code == 409
    r = client.post("/api/companies", json={"company_name": "Porter", "payment_model": "per_order"})
    assert r.status_code == 400
    r = client.post(
        "/api/companies",
        json={"company_name": "Porter", "payment_model": "per_order", "per_order_rate": 12.5},
    )
    assert r.status_code == 201, r.text
    assert r.json()["per_order_rate"] == 12.5 and r.json()["parser_type"] == "orders"
    assert (
        db.execute("SELECT per_order_rate FROM companies WHERE company_name='Porter'").fetchone()[0]
        == 1250
    )

    # Update: switch Flipkart to a payout file once they send one; deactivate Porter.
    r = client.patch(
        "/api/companies/Flipkart",
        json={
            "payment_model": "payout_file",
            "rider_id_column": "Rider",
            "payout_column": "Salary",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["payment_model"] == "payout_file" and r.json()["payout_column"] == "Salary"
    r = client.patch("/api/companies/Porter", json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.patch("/api/companies/Nope", json={"notes": "x"}).status_code == 404
    assert client.patch("/api/companies/Porter", json={"cadence": "daily"}).status_code == 400
    assert (
        client.patch("/api/companies/Porter", json={"rider_ids_shared_with": "Porter"}).status_code
        == 400
    )
    acts = db.execute(
        "SELECT action FROM activity_log WHERE entity_type='company' ORDER BY id"
    ).fetchall()
    assert [a["action"] for a in acts][:2] == ["company.create", "company.create"]
    assert "company.update" in {a["action"] for a in acts}


def test_monthly_next_cycle(client):
    client.post(
        "/api/companies",
        json={
            "company_name": "Monthly Co",
            "cadence": "monthly",
            "rider_id_column": "id",
            "payout_column": "pay",
        },
    )
    r = client.get("/api/companies/Monthly%20Co/next-cycle").json()
    assert r["cycle_start"].endswith("-01")


def test_direct_pay_company_has_nothing_to_process(client):
    r = client.post(
        "/api/cycles/run",
        data={
            "company": "Zomato",
            "cycle_start": "2026-06-01",
            "cycle_end": "2026-06-07",
            "commit": "false",
            "orders": json.dumps([{"rider_id": "Z1", "orders": 3}]),
        },
    )
    assert r.status_code == 400
    assert "pays its riders directly" in r.json()["detail"]


def test_per_order_cycle_pays_rate_times_orders_and_deducts_rent(db, client):
    pid = make_person(db, "SF Rider", balance=0, arrears=0)
    make_rider(db, pid, "SF-1", "Shadowfax", "SF Rider")
    make_ev(db, "EV-SF", provider="Raft", model="Regular")
    assign(db, pid, "EV-SF", charged_through="2026-05-31")
    db.execute(
        "UPDATE person_registry SET deduction_company='Shadowfax', deduction_rider_id='SF-1' "
        "WHERE person_id=?",
        (pid,),
    )
    pid2 = make_person(db, "Zero Rider", balance=0, arrears=0)
    make_rider(db, pid2, "SF-2", "Shadowfax", "Zero Rider")
    db.commit()

    # No file for a per-order company: the counts are the input.
    r = client.post(
        "/api/cycles/run",
        data={
            "company": "Shadowfax",
            "cycle_start": "2026-06-01",
            "cycle_end": "2026-06-07",
            "commit": "false",
        },
    )
    assert r.status_code == 400 and "enter the order counts" in r.json()["detail"]

    orders = json.dumps([{"rider_id": "SF-1", "orders": 200}, {"rider_id": "SF-2", "orders": 0}])
    r = client.post(
        "/api/cycles/run",
        data={
            "company": "Shadowfax",
            "cycle_start": "2026-06-01",
            "cycle_end": "2026-06-07",
            "commit": "false",
            "orders": orders,
        },
    )
    assert r.status_code == 200, r.text
    res = r.json()["result"]
    assert res["committed"] is False
    assert res["totals"]["riders_paid"] == 1  # the zero-order rider has nothing to release
    assert res["totals"]["total_release"] == 200 * 15.0 - WEEK_R
    assert res["totals"]["total_rent_charged"] == WEEK_R
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0

    r = client.post(
        "/api/cycles/run",
        data={
            "company": "Shadowfax",
            "cycle_start": "2026-06-01",
            "cycle_end": "2026-06-07",
            "commit": "true",
            "orders": orders,
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["result"]["committed"] is True and r.json()["xlsx"]["filename"]
    pay = db.execute(
        "SELECT amount FROM transactions WHERE person_id=? AND event_type='PAYOUT'", (pid,)
    ).fetchone()["amount"]
    assert pay == 200 * 1500  # paise
    assert (
        db.execute(
            "SELECT COUNT(*) FROM transactions WHERE person_id=? AND event_type='RENT_MISSED'",
            (pid2,),
        ).fetchone()[0]
        == 0
    )  # listed with 0 orders = present, not absent

    # Garbage counts are refused before anything runs.
    r = client.post(
        "/api/cycles/run",
        data={
            "company": "Shadowfax",
            "cycle_start": "2026-06-08",
            "cycle_end": "2026-06-14",
            "commit": "false",
            "orders": json.dumps([{"rider_id": "SF-1", "orders": -3}]),
        },
    )
    assert r.status_code == 400
