"""Zomato FE reports: three kinds of id, paid three ways.

ZFPP vendor report → Flat ids (orders × rate) and Salary ids (salary less
days short, plus incentives); MFFLEET vendor report → Commission ids, which
Zomato pays itself: listed, never paid, never charged as absent.
"""

from __future__ import annotations

import base64
import io
from datetime import date, timedelta

from openpyxl import Workbook, load_workbook

from payout.domain import zomato
from tests.conftest import make_person, make_rider
from tests.test_rent_due import _hdr, client  # noqa: F401  (fixture)

MON = date.today() - timedelta(days=date.today().weekday(), weeks=1)
HEAD = [
    "FE ID",
    "FE Name",
    "Total Orders",
    "Rain Orders",
    "Batched Orders",
    "Peak Login Hours Orders",
    "Total Login Hours",
    "Total Peak Login Hours",
    "Total Cancellations",
    "Total Denials",
    "Total Post Acceptance Denials",
    "Average Drop Distance",
    "Average Pickup Distance",
    "% Concentration Peak",
]


def report(vendor: str, day: date, rows) -> bytes:
    """The FE report as Zomato lays it out: two picker cells, a totals band,
    then the header row and one row per FE."""
    wb = Workbook()
    ws = wb.active
    ws.append([None, None])
    ws.append([None, "Select Vendor Name", f"Qwikserve logistic services LLP {vendor}"])
    ws.append([None, "Select Date", day.strftime("%Y%m%d")])
    ws.append([])
    ws.append([None, None, 5, 0, 0, 3, 4.2, 2.1, 0, 0, 0, 0.9, 1.1, "49%"])
    ws.append([None, *HEAD])
    for fe, name, orders, hours in rows:
        ws.append([None, fe, name, orders, 0, 0, 0, hours, 0, 0, 0, 0, 0, 0, "0%"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _roster(db):
    db.execute(
        "UPDATE companies SET per_order_rate=2500, salary_expected_days=26, "
        "incentive_per_order=1000, incentive_per_day=0 WHERE company_name='Zomato'"
    )
    flat = make_person(db, "Rakesh Jatua", balance=0, arrears=0)
    make_rider(db, flat, "FE1001", "Zomato", "Rakesh Jatua")
    sal = make_person(db, "Salma Bibi", balance=0, arrears=0)
    make_rider(db, sal, "FE1002", "Zomato", "Salma Bibi")
    com = make_person(db, "Comm Das", balance=0, arrears=0)
    make_rider(db, com, "FE1003", "Zomato", "Comm Das")
    unset = make_person(db, "No Type", balance=0, arrears=0)
    make_rider(db, unset, "FE1004", "Zomato", "No Type")
    db.execute("UPDATE rider_master SET payment_model='per_order' WHERE rider_id='FE1001'")
    db.execute(
        "UPDATE rider_master SET payment_model='salary', salary=2600000 WHERE rider_id='FE1002'"
    )
    db.execute("UPDATE rider_master SET payment_model='commission' WHERE rider_id='FE1003'")
    db.commit()


def test_the_report_layout_is_read():
    data = report("ZFPP", MON, [("FE12627272", "Rakesh Jatua", 5, 4.245)])
    grid = [list(r) for r in load_workbook(io.BytesIO(data)).active.values]
    vendor, day, rows = zomato.read_sheet("x", grid)
    assert vendor.endswith("ZFPP") and day == MON.isoformat()
    assert rows[0]["fe_id"] == "FE12627272" and rows[0]["orders"] == 5
    assert rows[0]["login_hours"] == 4.245
    assert zomato.vendor_kind("Qwikserve logistic services LLP MFFLEET") == "commission"


def _run(client, files, commit=False):  # noqa: F811
    boss = _hdr(client)
    return client.post(
        "/api/cycles/run",
        data={
            "company": "Zomato",
            "cycle_start": MON.isoformat(),
            "cycle_end": (MON + timedelta(days=6)).isoformat(),
            "commit": "true" if commit else "false",
        },
        files=[("files", (n, b, "application/octet-stream")) for n, b in files],
        headers=boss,
    )


def _week(db):
    files = []
    for i in range(3):
        d = MON + timedelta(days=i)
        files.append(
            (
                f"zfpp_{i}.xlsx",
                report(
                    "ZFPP",
                    d,
                    [
                        ("FE1001", "Rakesh Jatua", 10, 8),
                        ("FE1002", "Salma Bibi", 4, 9),
                        ("FE1004", "No Type", 7, 6),
                    ],
                ),
            )
        )
        files.append((f"mf_{i}.xlsx", report("MFFLEET", d, [("FE1003", "Comm Das", 12, 10)])))
    return files


def test_each_kind_is_paid_its_own_way(db, client):  # noqa: F811
    _roster(db)
    r = _run(client, _week(db))
    assert r.status_code == 200, r.text
    z = {x["rider_id"]: x for x in r.json()["zomato"]["riders"]}
    # Flat: 30 orders × ₹25
    assert z["FE1001"]["type"] == "Flat" and z["FE1001"]["gross"] == 750.0
    # Salary: ₹26,000 less 23 days short of 26, plus 12 orders × ₹10
    assert z["FE1002"]["type"] == "Salary"
    assert z["FE1002"]["gross"] == round(26000 - 23 * 1000 + 120, 2)
    # Commission: listed, not paid
    assert z["FE1003"]["type"] == "Commission" and z["FE1003"]["gross"] == 0
    # ZFPP id with no type: not guessed
    assert z["FE1004"]["type"] == "Not set"
    paid = {x["rider_id"] for x in r.json()["result"]["pay_rows"] + r.json()["result"]["dues_rows"]}
    assert paid == {"FE1001", "FE1002"}
    assert any("no type" in w for w in r.json()["result"]["warnings"])


def test_an_untyped_id_blocks_commit(db, client):  # noqa: F811
    _roster(db)
    r = _run(client, _week(db), commit=True)
    assert r.status_code == 400 and "need a type" in r.text


def test_a_committed_day_is_not_paid_twice(db, client):  # noqa: F811
    _roster(db)
    db.execute("UPDATE rider_master SET payment_model='per_order' WHERE rider_id='FE1004'")
    db.commit()
    files = _week(db)
    r = _run(client, files, commit=True)
    assert r.status_code == 200, r.text
    wb = load_workbook(io.BytesIO(base64.b64decode(r.json()["xlsx"]["content_base64"])))
    assert "Zomato detail" in wb.sheetnames and "COMMISSION" in wb.sheetnames
    r2 = _run(client, files)
    assert r2.status_code == 200, r2.text
    assert not r2.json()["result"]["pay_rows"] and not r2.json()["result"]["dues_rows"]
    assert len(r2.json()["zomato"]["already_paid"]) == 9


def test_a_commission_rider_with_an_ev_is_not_charged_as_absent(db, client):  # noqa: F811
    from tests.conftest import make_ev

    _roster(db)
    db.execute("UPDATE rider_master SET payment_model='per_order' WHERE rider_id='FE1004'")
    pid = db.execute("SELECT person_id FROM rider_master WHERE rider_id='FE1003'").fetchone()[0]
    make_ev(db, "KOLZOM1", status="in_use")
    db.execute(
        "INSERT INTO ev_assignments (person_id, ev_id, handover_date) VALUES (?,?,?)",
        (pid, "KOLZOM1", (MON - timedelta(days=10)).isoformat()),
    )
    db.commit()
    r = _run(client, _week(db), commit=True)
    assert r.status_code == 200, r.text
    missed = db.execute(
        "SELECT COUNT(*) FROM transactions WHERE person_id=? AND event_type='RENT_MISSED'", (pid,)
    ).fetchone()[0]
    assert missed == 0


def test_commission_ids_can_be_chosen_at_onboarding(db, client):  # noqa: F811
    boss = _hdr(client)
    r = client.post(
        "/api/riders",
        json={
            "company": "Zomato",
            "name": "New Comm",
            "rider_id": "FE2001",
            "payment_model": "commission",
        },
        headers=boss,
    )
    assert r.status_code == 201, r.text
    assert r.json()["payment_model"] == "commission"
    bad = client.post(
        "/api/riders",
        json={
            "company": "Zomato",
            "name": "Bad Type",
            "rider_id": "FE2002",
            "payment_model": "weekly",
        },
        headers=boss,
    )
    assert bad.status_code == 400


def test_editing_the_company_keeps_the_fe_parser_and_flat_rate(db, client):  # noqa: F811
    boss = _hdr(client)
    r = client.patch(
        "/api/companies/Zomato",
        json={"per_order_rate": 30, "incentive_per_order": 5, "notes": "FE reports"},
        headers=boss,
    )
    assert r.status_code == 200, r.text
    row = db.execute(
        "SELECT parser_type, per_order_rate, payment_model FROM companies "
        "WHERE company_name='Zomato'"
    ).fetchone()
    assert row["parser_type"] == "zomato" and row["per_order_rate"] == 3000
    assert row["payment_model"] == "direct"
