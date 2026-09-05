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


def test_pidge_delhivery_seeded_and_defaults_direct(db, client):
    rows = {c["company_name"]: c for c in client.get("/api/companies").json()}
    assert rows["Pidge"]["payment_model"] == "direct"
    assert rows["Delhivery"]["payment_model"] == "direct"
    # A company added with nothing but a name is direct-pay until told otherwise.
    r = client.post("/api/companies", json={"company_name": "Ekart"})
    assert r.status_code == 201 and r.json()["payment_model"] == "direct"
    # Migration 0016 on an existing DB: Blue Dart + Dealshare switched off, nothing lost.
    from payout.db.migrations import _0016_pidge_delhivery_retire_bluedart_dealshare

    _0016_pidge_delhivery_retire_bluedart_dealshare(db)
    db.commit()
    rows = {c["company_name"]: c for c in client.get("/api/companies").json()}
    assert rows["Dealshare"]["is_active"] is False
    assert (
        db.execute("SELECT COUNT(*) FROM companies WHERE company_name='Pidge'").fetchone()[0] == 1
    )


def _salary_company(client):
    r = client.post(
        "/api/companies",
        json={
            "company_name": "SalaryCo",
            "payment_model": "salary",
            "cadence": "monthly",
            "salary_expected_days": 26,
            "incentive_per_order": 2,  # ₹2 an order
            "incentive_per_day": 10,  # ₹10 a day present
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["parser_type"] == "salary"
    assert body["incentive_per_order"] == 2.0 and body["incentive_per_day"] == 10.0
    assert body["salary_expected_days"] == 26


def test_salary_cycle_deducts_days_off_and_adds_incentives(db, client):
    _salary_company(client)
    pid = make_person(db, "Sal Rider", balance=0, arrears=0)
    make_rider(db, pid, "S-1", "SalaryCo", "Sal Rider")
    make_ev(db, "EV-S", provider="Raft", model="Regular")
    assign(db, pid, "EV-S", charged_through="2026-05-31")
    db.execute(
        "UPDATE person_registry SET deduction_company='SalaryCo', deduction_rider_id='S-1' "
        "WHERE person_id=?",
        (pid,),
    )
    db.commit()
    # Salary is set on the rider row (rupees in, paise stored, rupees out).
    r = client.patch("/api/riders/S-1?company=SalaryCo", json={"salary": 13000})
    assert r.status_code == 200, r.text
    assert r.json()["salary"] == 13000.0
    assert (
        db.execute("SELECT salary FROM rider_master WHERE rider_id='S-1'").fetchone()[0] == 1300000
    )

    attendance = json.dumps([{"rider_id": "S-1", "days_present": 24, "orders": 300}])
    common = {"company": "SalaryCo", "cycle_start": "2026-06-01", "cycle_end": "2026-06-30"}
    r = client.post("/api/cycles/run", data={**common, "commit": "false"})
    assert r.status_code == 400 and "salaried" in r.json()["detail"]
    r = client.post("/api/cycles/run", data={**common, "commit": "false", "attendance": attendance})
    assert r.status_code == 200, r.text
    body = r.json()
    line = body["salary_lines"][0]
    # 2 days off of 26: 13000 − 2 × 500 = 12000; incentives 300×2 + 24×10 = 840.
    assert line["days_off"] == 2
    assert line["base_pay"] == 12000.0 and line["incentives"] == 840.0
    assert line["payout"] == 12840.0
    res = body["result"]
    assert res["totals"]["riders_paid"] == 1
    assert res["totals"]["total_rent_charged"] > 0  # EV rent comes off the salary as usual
    assert db.execute("SELECT COUNT(*) FROM salary_inputs").fetchone()[0] == 0

    r = client.post("/api/cycles/run", data={**common, "commit": "true", "attendance": attendance})
    assert r.status_code == 200, r.text
    assert r.json()["result"]["committed"] is True
    row = db.execute("SELECT * FROM salary_inputs WHERE rider_id='S-1'").fetchone()
    assert (row["days_present"], row["orders"], row["payout"]) == (24, 300, 1284000)
    assert (
        db.execute(
            "SELECT amount FROM transactions WHERE person_id=? AND event_type='PAYOUT'", (pid,)
        ).fetchone()[0]
        == 1284000
    )

    # A rider without a salary set is refused by name, not silently paid nothing.
    pid2 = make_person(db, "No Salary")
    make_rider(db, pid2, "S-2", "SalaryCo", "No Salary")
    db.commit()
    r = client.post(
        "/api/cycles/run",
        data={
            "company": "SalaryCo",
            "cycle_start": "2026-07-01",
            "cycle_end": "2026-07-31",
            "commit": "false",
            "attendance": json.dumps([{"rider_id": "S-2", "days_present": 26, "orders": 0}]),
        },
    )
    assert r.status_code == 400 and "No Salary has no salary set" in r.json()["detail"]


def test_parse_attendance_sheet(db, client):
    _salary_company(client)
    pid = make_person(db, "Sal Rider")
    make_rider(db, pid, "S-1", "SalaryCo", "Sal Rider")
    db.commit()
    import io

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Rider ID", "Name", "Days Present", "Orders Delivered"])
    ws.append(["S-1", "Sal Rider", 24, 300])
    ws.append(["S-9", "Stranger", 20, 10])
    ws.append([None, None, None, None])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post(
        "/api/cycles/parse-sheet",
        data={"company": "SalaryCo"},
        files={"file": ("att.xlsx", buf.getvalue(), "application/octet-stream")},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["rows"] == [
        {"rider_id": "S-1", "name": "Sal Rider", "days_present": 24.0, "orders": 300.0}
    ]
    assert [u["rider_id"] for u in body["unknown"]] == ["S-9"]
    assert body["matched"]["days_present"] == "Days Present"
