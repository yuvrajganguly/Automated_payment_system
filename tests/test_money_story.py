"""The money-story endpoints (/dashboard/story, /dashboard/story/by).

One seeded reality, told three ways: a present rider pays rent, an absent
rider's rent falls to arrears, part of that debt is later written off by a
backdated EV return. The story must report charged / collected / missed /
recovered / written-off numbers that add up, in every grouping.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from openpyxl import Workbook

from payout.domain.engine import process_cycle
from tests.conftest import assign, make_ev, make_person, make_rider

WEEK_R = 1250.0  # rupees


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


@pytest.fixture
def seeded(db, client):
    """Payer (P1, EV-P) pays; Ghost (G1, EV-G) is absent; Ghost's EV is then
    returned backdated to the cycle start — full write-off."""
    wk = date.today() - timedelta(days=date.today().weekday(), weeks=1)  # last Monday
    for rid, ev in (("P1", "EV-P"), ("G1", "EV-G")):
        pid = make_person(db, f"N-{rid}", balance=0, arrears=0)
        make_rider(db, pid, rid, "Blitz", f"N-{rid}")
        make_ev(db, ev, provider="Raft", model="Regular")
        assign(db, pid, ev, charged_through=(wk - timedelta(days=1)).isoformat())
        db.execute(
            "UPDATE person_registry SET deduction_company='Blitz', deduction_rider_id=? "
            "WHERE person_id=?",
            (rid, pid),
        )
    db.commit()
    process_cycle("Blitz", wk, wk + timedelta(days=6), _file([("P1", 5000)]), commit=True)
    r = client.post("/api/evs/return", json={"ev_id": "EV-G", "returned_date": wk.isoformat()})
    assert r.status_code == 200 and r.json()["heal"]["arrears_written_off"] == WEEK_R
    return wk


def test_story_flow_adds_up(seeded, client):
    body = client.get("/api/dashboard/story").json()
    f = body["flow"]
    assert f["gross_payout"] == 5000.0
    assert f["rent_charged"] == WEEK_R  # P1's week
    assert f["rent_collected"] == WEEK_R
    assert f["rent_missed"] == WEEK_R  # G1's week
    assert f["written_off"] == WEEK_R  # healed by the backdated return
    assert f["released"] == 5000.0 - WEEK_R
    # position: the write-off cleared the books entirely
    p = body["position"]
    assert p["ev_arrears"] == 0 and p["ev_arrears_dormant"] == 0
    assert p["dues"] == 0
    # company filter that matches nothing zeroes the flow
    empty = client.get("/api/dashboard/story?companies=Myntra").json()["flow"]
    assert empty["gross_payout"] == 0 and empty["written_off"] == 0


def test_story_dormant_position(db, client):
    """Un-healed dormant debt shows in the live position, split out."""
    pid = make_person(db, "Dorm", balance=0, arrears=70000)
    make_ev(db, "EV-D", provider="Raft", model="Regular")
    assign(db, pid, "EV-D", returned="2026-05-20", charged_through="2026-05-19")
    db.commit()
    p = client.get("/api/dashboard/story").json()["position"]
    assert p["ev_arrears"] == 700.0
    assert p["ev_arrears_dormant"] == 700.0 and p["ev_arrears_active"] == 0
    assert p["dormant_riders"] == 1


def test_story_by_company(seeded, client):
    rows = client.get("/api/dashboard/story/by?dim=company").json()["rows"]
    blitz = next(r for r in rows if r["company"] == "Blitz")
    assert blitz["rent_charged"] == WEEK_R
    assert blitz["rent_missed"] == WEEK_R
    assert blitz["written_off"] == WEEK_R
    assert blitz["riders"] == 1  # only P1 had a payout


def test_story_by_rider(seeded, client):
    rows = client.get("/api/dashboard/story/by?dim=rider").json()["rows"]
    by_name = {r["display_name"]: r for r in rows}
    assert by_name["N-P1"]["rent_collected"] == WEEK_R
    assert by_name["N-P1"]["released"] == 5000.0 - WEEK_R
    assert by_name["N-G1"]["rent_missed"] == WEEK_R
    assert by_name["N-G1"]["written_off"] == WEEK_R
    assert by_name["N-G1"]["outstanding"] == 0


def test_story_by_ev(seeded, client):
    rows = client.get("/api/dashboard/story/by?dim=ev").json()["rows"]
    evs = {r["ev_id"]: r for r in rows}
    # Payer's EV: a week charged and collected (±1p day rounding).
    assert abs(evs["EV-P"]["charged"] - WEEK_R) < 0.1
    assert abs(evs["EV-P"]["collected"] - WEEK_R) < 0.1
    assert evs["EV-P"]["missed"] == 0
    # Ghost's EV was healed out of the ledger but still shows its write-off.
    assert evs["EV-G"]["written_off"] == WEEK_R
    assert evs["EV-G"]["missed"] == 0


def test_story_by_bad_dim(client):
    assert client.get("/api/dashboard/story/by?dim=nope").status_code == 400
