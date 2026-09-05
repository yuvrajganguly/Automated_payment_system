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


def test_window_is_by_cycle_not_processing_date(db, client):
    """A cycle for a week in June processed today belongs to June. Any overlap
    with the window counts; a window that only covers today sees nothing."""
    pid = make_person(db, "June Rider", balance=0, arrears=0)
    make_rider(db, pid, "J1", "Blitz", "June Rider")
    make_ev(db, "EV-J", provider="Raft", model="Regular")
    assign(db, pid, "EV-J", charged_through="2026-05-31")
    db.execute(
        "UPDATE person_registry SET deduction_company='Blitz', deduction_rider_id='J1' "
        "WHERE person_id=?",
        (pid,),
    )
    db.commit()
    process_cycle("Blitz", date(2026, 6, 1), date(2026, 6, 7), _file([("J1", 4000)]), commit=True)

    def flow(qs):
        return client.get("/api/dashboard/story" + qs).json()["flow"]

    assert flow("?date_from=2026-06-01&date_to=2026-06-07")["gross_payout"] == 4000.0
    # One day of overlap on either edge is enough.
    assert flow("?date_from=2026-05-25&date_to=2026-06-01")["gross_payout"] == 4000.0
    assert flow("?date_from=2026-06-07&date_to=2026-06-20")["gross_payout"] == 4000.0
    # Adjacent but not overlapping: nothing.
    assert flow("?date_from=2026-06-08&date_to=2026-06-14")["gross_payout"] == 0
    # The day it was processed (today) is not the cycle's window.
    today = date.today().isoformat()
    assert flow(f"?date_from={today}&date_to={today}")["gross_payout"] == 0
    rows = client.get(
        "/api/dashboard/story/by?dim=company&date_from=2026-06-01&date_to=2026-06-07"
    ).json()["rows"]
    assert [r["company"] for r in rows] == ["Blitz"] and rows[0]["gross_payout"] == 4000.0


def test_story_weeks_tally_with_prior_dues_and_carry_forward(db, client):
    """Week-by-week per company: a rider who ends week 1 in debt shows it as
    carried forward; the debt recovered from week 2's payout shows as prior
    dues collected in week 2's row."""
    pid = make_person(db, "Carry Rider", balance=0, arrears=0)
    make_rider(db, pid, "C1", "Blitz", "Carry Rider")
    make_ev(db, "EV-C", provider="Raft", model="Regular")
    assign(db, pid, "EV-C", charged_through="2026-05-31")
    db.execute(
        "UPDATE person_registry SET deduction_company='Blitz', deduction_rider_id='C1' "
        "WHERE person_id=?",
        (pid,),
    )
    db.commit()
    # Week 1: payout smaller than the rent -> dues carried forward.
    process_cycle("Blitz", date(2026, 6, 1), date(2026, 6, 7), _file([("C1", 500)]), commit=True)
    # Week 2: a normal payout clears last week's dues.
    process_cycle("Blitz", date(2026, 6, 8), date(2026, 6, 14), _file([("C1", 5000)]), commit=True)

    body = client.get("/api/dashboard/story/weeks?date_from=2026-06-01&date_to=2026-06-14").json()
    rows = body["rows"]
    assert [(r["company"], r["cycle_start"]) for r in rows] == [
        ("Blitz", "2026-06-08"),
        ("Blitz", "2026-06-01"),
    ]
    w1 = rows[1]
    w2 = rows[0]
    shortfall = WEEK_R - 500.0
    assert w1["gross_payout"] == 500.0 and w1["rent_charged"] == WEEK_R
    assert w1["carried_forward"] == shortfall and w1["released"] == 0
    assert w1["partial"] is False
    assert w2["prior_dues_collected"] == shortfall
    assert w2["carried_forward"] == 0
    assert w2["released"] == 5000.0 - WEEK_R - shortfall
    # A window touching only week 2 marks week 1 as outside... and drops it.
    rows = client.get("/api/dashboard/story/weeks?date_from=2026-06-10&date_to=2026-06-20").json()[
        "rows"
    ]
    assert [r["cycle_start"] for r in rows] == ["2026-06-08"] and rows[0]["partial"] is True


def test_company_page_history_and_header(db, client):
    """The company page asks for every cycle (all_time) and a lifetime header."""
    pid = make_person(db, "Hist Rider", balance=0, arrears=0)
    make_rider(db, pid, "H1", "Blitz", "Hist Rider")
    make_ev(db, "EV-H", provider="Raft", model="Regular")
    assign(db, pid, "EV-H", charged_through="2026-05-31")
    db.execute(
        "UPDATE person_registry SET deduction_company='Blitz', deduction_rider_id='H1' "
        "WHERE person_id=?",
        (pid,),
    )
    db.commit()
    process_cycle("Blitz", date(2026, 6, 1), date(2026, 6, 7), _file([("H1", 5000)]), commit=True)
    process_cycle("Blitz", date(2026, 7, 6), date(2026, 7, 12), _file([("H1", 4000)]), commit=True)

    # A narrow window sees one cycle; all_time sees both, none marked partial.
    narrow = client.get("/api/dashboard/story/weeks?date_from=2026-07-01&date_to=2026-07-14")
    assert [r["cycle_start"] for r in narrow.json()["rows"]] == ["2026-07-06"]
    body = client.get("/api/dashboard/story/weeks?all_time=1&companies=Blitz").json()
    assert [r["cycle_start"] for r in body["rows"]] == ["2026-07-06", "2026-06-01"]
    assert all(r["partial"] is False for r in body["rows"])
    assert body["window"]["all_time"] is True and body["window"]["from"] == "2026-06-01"

    head = client.get("/api/dashboard/story/company/Blitz").json()
    assert head["company_name"] == "Blitz"
    assert head["cycles"] == 2 and head["riders"] == 1
    assert head["first_cycle"] == "2026-06-01" and head["last_cycle"] == "2026-07-12"
    assert head["gross_payout"] == 9000.0
    # Lifetime totals are the sum of the week rows (the July cycle also
    # carries the catch-up rent for the gap, so it is more than two weeks).
    assert head["rent_collected"] == sum(r["rent_collected"] for r in body["rows"]) >= 2 * WEEK_R
    assert head["active_riders"] >= 1
    assert client.get("/api/dashboard/story/company/Nope").status_code == 404
