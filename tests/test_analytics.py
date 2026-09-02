"""Dashboard analytics endpoints (routes/analytics.py).

Real data path: two weekly Blitz cycles through process_cycle — one where the
EV holder was ABSENT (rent falls to arrears), one where they were PRESENT with
a payout large enough to recover everything. The endpoints must tell that
story back: the missed week, the recovery, the fleet margin, the rider counts.
Money asserted in rupees — the egress middleware converts every MONEY_KEYS
field.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from openpyxl import Workbook

from payout.domain.engine import process_cycle
from tests.conftest import assign, make_ev, make_person, make_rider

RAFT_WEEK_R = 1250.0  # rupees


def _file(rows, headers=("rider_id", "net_pay")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _week(cycle_start: date) -> str:
    y, w, _ = cycle_start.isocalendar()
    return f"{y}-W{w:02d}"


def _mondays_back(n: int) -> date:
    today = date.today()
    return today - timedelta(days=today.weekday(), weeks=n)


@pytest.fixture
def seeded(db):
    """One Raft EV holder; absent two weeks ago, paid last week."""
    pid = make_person(db, "Trend Rider", balance=0, arrears=0)
    make_rider(db, pid, "T1", "Blitz", "Trend Rider")
    make_ev(db, "EV-T", provider="Raft", model="Regular")
    wk_a_start = _mondays_back(2)
    assign(db, pid, "EV-T", charged_through=(wk_a_start - timedelta(days=1)).isoformat())
    db.execute(
        "UPDATE person_registry SET deduction_company='Blitz', deduction_rider_id='T1' "
        "WHERE person_id=?",
        (pid,),
    )
    db.commit()
    wk_b_start = _mondays_back(1)
    # Week A: absent -> RENT_MISSED to arrears.
    process_cycle(
        "Blitz", wk_a_start, wk_a_start + timedelta(days=6), _file([("OTHER", 10)]), commit=True
    )
    # Week B: present, payout covers rent + arrears with money left over.
    process_cycle(
        "Blitz", wk_b_start, wk_b_start + timedelta(days=6), _file([("T1", 6000)]), commit=True
    )
    return {"pid": pid, "wk_a": _week(wk_a_start), "wk_b": _week(wk_b_start)}


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


def _by_week(payload: dict, key: str = "weeks") -> dict:
    return {w["week"]: w for w in payload[key]}


def test_trends_tells_the_two_week_story(seeded, client):
    r = client.get("/api/dashboard/trends?weeks=12")
    assert r.status_code == 200, r.text
    weeks = _by_week(r.json())
    a, b = weeks[seeded["wk_a"]], weeks[seeded["wk_b"]]
    # Week A: rider absent — a week of rent fell to arrears, nothing moved.
    assert a["rent_missed"] == RAFT_WEEK_R
    assert a["released"] == 0 and a["rent_collected"] == 0
    # Week B: ₹6,000 gross; a week's rent collected; the missed week recovered.
    assert b["gross_payout"] == 6000.0
    assert b["rent_charged"] == RAFT_WEEK_R
    assert b["rent_collected"] == RAFT_WEEK_R
    assert b["arrears_recovered"] == RAFT_WEEK_R
    assert b["released"] == 6000.0 - 2 * RAFT_WEEK_R
    # company filter that matches nothing zeroes the series
    empty = _by_week(client.get("/api/dashboard/trends?weeks=12&companies=Myntra").json())
    assert empty[seeded["wk_b"]]["gross_payout"] == 0


def test_collection_rate_and_recovery(seeded, client):
    r = client.get("/api/dashboard/collection?weeks=12")
    assert r.status_code == 200, r.text
    body = r.json()
    weeks = {w["week"]: w for w in body["weekly"]}
    a = weeks[seeded["wk_a"]]
    # Week A's missed days were healed by week B's recovery -> collected now.
    assert a["expected"] == RAFT_WEEK_R
    assert a["collected"] == RAFT_WEEK_R and a["missed"] == 0
    assert a["collection_rate"] == 100.0
    # Everything recovered -> no aging buckets left.
    assert sum(bucket["riders"] for bucket in body["aging"]) == 0
    assert body["velocity_4w"]["recovered"] == RAFT_WEEK_R
    assert body["velocity_4w"]["missed"] == RAFT_WEEK_R


def test_aging_shows_unrecovered_debt(db, client):
    """Only the absent week has run: the rider must sit in a young bucket."""
    pid = make_person(db, "Aging", balance=0, arrears=0)
    make_rider(db, pid, "G1", "Blitz", "Aging")
    make_ev(db, "EV-G", provider="Raft", model="Regular")
    wk = _mondays_back(1)
    assign(db, pid, "EV-G", charged_through=(wk - timedelta(days=1)).isoformat())
    db.execute(
        "UPDATE person_registry SET deduction_company='Blitz', deduction_rider_id='G1' "
        "WHERE person_id=?",
        (pid,),
    )
    db.commit()
    process_cycle("Blitz", wk, wk + timedelta(days=6), _file([("OTHER", 10)]), commit=True)
    body = client.get("/api/dashboard/collection?weeks=12").json()
    young = body["aging"][0]  # 0-14d
    assert young["riders"] == 1
    assert young["outstanding"] == RAFT_WEEK_R


def test_fleet_economics(seeded, client):
    r = client.get("/api/dashboard/fleet")
    assert r.status_code == 200, r.text
    body = r.json()
    evs = {e["ev_id"]: e for e in body["evs"]}
    ev = evs["EV-T"]
    # Two materialized weeks: all healed to collected -> earned ~two weeks' rent.
    # (Day-level rows carry the rounded ₹178.57 daily rate, so a week can be a
    # paisa or two off ₹1,250 — the ledger reconciles at the RENT row level.)
    assert abs(ev["earned"] - 2 * RAFT_WEEK_R) < 0.1
    assert abs(ev["provider_owed"] - 2 * RAFT_WEEK_R) < 0.1
    assert round(ev["margin"], 2) == round(ev["earned"] - ev["provider_owed"], 2)
    assert ev["billable_days"] == 14 and ev["ledger_days"] == 14
    assert ev["utilization"] == 100.0
    assert ev["holder"] == "Trend Rider"
    raft = next(p for p in body["providers"] if p["provider"] == "Raft")
    assert raft["evs"] == 1 and abs(raft["earned"] - 2 * RAFT_WEEK_R) < 0.1


def test_rider_analytics(seeded, client):
    r = client.get("/api/dashboard/riders?weeks=12")
    assert r.status_code == 200, r.text
    body = r.json()
    weeks = {w["week"]: w for w in body["weekly"]}
    b = weeks[seeded["wk_b"]]
    assert b["paid"] == 1
    assert b["new"] == 1  # first-ever payout landed in week B
    top = body["top_earners"]
    assert top and top[0]["display_name"] == "Trend Rider"
    assert top[0]["released"] == 6000.0 - 2 * RAFT_WEEK_R


def test_weeks_param_is_validated(client):
    assert client.get("/api/dashboard/trends?weeks=0").status_code == 400
    assert client.get("/api/dashboard/trends?weeks=99").status_code == 400
