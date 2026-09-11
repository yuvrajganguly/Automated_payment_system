"""Two deliberate changes of behaviour, 2026-09-10.

**The fence is now total.** A recruiter with a zone sees that zone and nothing
else: not the other zone, not Misc, and not the stores nobody has classified.
Unclassified stores used to ride along on the reasoning that a store no admin
had placed would otherwise be invisible to the whole field at once — every
recruiter being fenced somewhere. That held while there was no way to place a
store; since the company tab grew a stores panel there is, so an unplaced
store is now a job rather than a hole. ``zone=unassigned`` is refused for a
fenced caller too, or the fence would be a chip you could route around.

**A recruiter recruits people, not rider ids.** Every recruit count is one row
per person, dated from the first id that person got under that recruiter. This
mattered the moment the app grew a deliberate "add an id at another company"
action: the double count stopped being an accident in the data and became
something we cause.
"""

from __future__ import annotations

import pytest

from tests.conftest import make_person, make_rider


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
            ("north@t.test", hash_password("Recruit-pass-1"), "recruiter"),
            ("nozone@t.test", hash_password("Recruit-pass-2"), "recruiter"),
            ("boss@t.test", hash_password("Creator-pass-1"), "creator"),
        ],
    )
    db.execute("UPDATE users SET zone='North' WHERE email='north@t.test'")
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        yield c


def _hdr(client, email, pw):
    r = client.post("/api/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


@pytest.fixture
def board(db, client):
    """One rider per bucket: North, South, Misc and an unplaced store."""
    boss = _hdr(client, "boss@t.test", "Creator-pass-1")
    for rid, name, hub in (
        ("SF-N", "North Rider", "Salt Lake"),
        ("SF-S", "South Rider", "Garia"),
        ("SF-M", "Misc Rider", "Varanasi"),
        ("SF-U", "Unplaced Rider", "Howrah"),
    ):
        pid = make_person(db, name)
        make_rider(db, pid, rid, "Shadowfax", name)
        db.execute("UPDATE rider_master SET hub=? WHERE rider_id=?", (hub, rid))
    db.commit()
    for hub, zone in (("Salt Lake", "North"), ("Garia", "South"), ("Varanasi", "Misc")):
        assert (
            client.put(f"/api/hubs/Shadowfax/{hub}", json={"zone": zone}, headers=boss).status_code
            == 200
        )
    # Howrah is left deliberately unclassified.
    return boss


# ── the fence ────────────────────────────────────────────────────────────────


def test_fenced_recruiter_sees_only_their_own_zone(client, board):
    north = _hdr(client, "north@t.test", "Recruit-pass-1")
    got = {r["rider_id"] for r in client.get("/api/riders", headers=north).json()}
    assert got == {"SF-N"}, "Misc and the unplaced store must not come along"


def test_asking_for_all_does_not_widen_the_fence(client, board):
    north = _hdr(client, "north@t.test", "Recruit-pass-1")
    got = {r["rider_id"] for r in client.get("/api/riders?zone=all", headers=north).json()}
    assert got == {"SF-N"}


def test_a_fenced_recruiter_cannot_name_misc(client, board):
    north = _hdr(client, "north@t.test", "Recruit-pass-1")
    assert client.get("/api/riders?zone=Misc", headers=north).status_code == 403
    assert client.get("/api/riders?zone=South", headers=north).status_code == 403


def test_unassigned_is_not_a_way_round_the_fence(client, board):
    """It would hand back exactly the bucket the fence excludes."""
    north = _hdr(client, "north@t.test", "Recruit-pass-1")
    assert client.get("/api/riders?zone=unassigned", headers=north).status_code == 403


def test_admins_still_find_the_unplaced_stores(client, board):
    """The fence is for field staff; somebody has to be able to see the work
    that needs classifying, or it never gets classified."""
    boss = board
    got = {r["rider_id"] for r in client.get("/api/riders?zone=unassigned", headers=boss).json()}
    assert got == {"SF-U"}
    everyone = {r["rider_id"] for r in client.get("/api/riders", headers=boss).json()}
    assert everyone == {"SF-N", "SF-S", "SF-M", "SF-U"}


def test_a_recruiter_with_no_zone_is_not_fenced(client, board):
    """A new joiner nobody has placed yet must not stare at an empty app."""
    free = _hdr(client, "nozone@t.test", "Recruit-pass-2")
    got = {r["rider_id"] for r in client.get("/api/riders", headers=free).json()}
    assert got == {"SF-N", "SF-S", "SF-M", "SF-U"}


def test_the_fence_holds_on_the_todo_list(client, board):
    north = _hdr(client, "north@t.test", "Recruit-pass-1")
    t = client.get("/api/app/todo", headers=north).json()
    assert t["zone"] == "North"
    assert all(s["zone"] == "North" for s in t["stores"]), t["stores"]
    assert client.get("/api/app/todo?zone=unassigned", headers=north).status_code == 403
    assert client.get("/api/app/todo?zone=Misc", headers=north).status_code == 403


def test_the_bootstrap_offers_one_zone_only(client, board):
    north = _hdr(client, "north@t.test", "Recruit-pass-1")
    b = client.get("/api/app/bootstrap", headers=north).json()
    assert b["zones"] == ["North"], "no chip for a zone the route would refuse"
    free = _hdr(client, "nozone@t.test", "Recruit-pass-2")
    assert client.get("/api/app/bootstrap", headers=free).json()["zones"] == [
        "North",
        "South",
        "Misc",
    ]


# ── counting people, not rider ids ───────────────────────────────────────────


def _onboard(client, hdr, name, company="Shadowfax", rider_id=None, person_id=None):
    r = client.post(
        "/api/riders",
        json={"company": company, "name": name, "rider_id": rider_id, "person_id": person_id},
        headers=hdr,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_a_second_company_id_is_not_a_second_recruit(db, client):
    boss = _hdr(client, "boss@t.test", "Creator-pass-1")
    north = _hdr(client, "north@t.test", "Recruit-pass-1")
    a = _onboard(client, north, "Arjun Das", rider_id="SF-1")
    _onboard(client, north, "Arjun Das", company="Kaptan", rider_id="K-1", person_id=a["person_id"])
    _onboard(client, north, "Bikash Roy", rider_id="SF-2")

    c = client.get("/api/app/my-recruiting", headers=north).json()["counts"]
    assert c["all_time"] == 2, "three rider ids, two people"
    assert c["persons"] == c["all_time"]
    assert c["on_roster"] == 2

    row = next(
        r
        for r in client.get("/api/app/recruiting", headers=boss).json()["recruiters"]
        if r["email"] == "north@t.test"
    )
    assert (row["all_time"], row["active"]) == (2, 2)

    console = next(
        r
        for r in client.get("/api/recruiters", headers=boss).json()["recruiters"]
        if r["email"] == "north@t.test"
    )
    assert console["onboarded_all_time"] == 2
    assert console["onboarded_month"] == 2


def test_the_cohort_is_dated_from_the_first_id(db, client):
    """A rider signed up in January who picks up a second company id today is
    a January recruit, not a new one — otherwise a recruiter could inflate
    this week's number by re-tagging an old rider."""
    boss = _hdr(client, "boss@t.test", "Creator-pass-1")
    north = _hdr(client, "north@t.test", "Recruit-pass-1")
    a = _onboard(client, north, "Arjun Das", rider_id="SF-1")
    db.execute(
        "UPDATE rider_master SET created_at='2025-01-05 10:00:00' WHERE rider_id='SF-1'",
    )
    db.commit()
    _onboard(client, north, "Arjun Das", company="Kaptan", rider_id="K-1", person_id=a["person_id"])

    c = client.get("/api/app/my-recruiting", headers=north).json()["counts"]
    assert c["all_time"] == 1
    assert (c["today"], c["week"], c["month"]) == (0, 0, 0), "an old recruit, not a new one"

    console = next(
        r
        for r in client.get("/api/recruiters", headers=boss).json()["recruiters"]
        if r["email"] == "north@t.test"
    )
    assert console["onboarded_all_time"] == 1
    assert console["onboarded_month"] == 0

    # And the chart puts them in one bucket, not two.
    s = client.get("/api/recruiters/north@t.test/series?grain=month", headers=boss).json()
    assert sum(b["onboarded"] for b in s["series"]) <= 1


def test_per_company_columns_add_up_to_the_total(db, client):
    north = _hdr(client, "north@t.test", "Recruit-pass-1")
    a = _onboard(client, north, "Arjun Das", rider_id="SF-1")
    _onboard(client, north, "Arjun Das", company="Kaptan", rider_id="K-1", person_id=a["person_id"])
    # Two ids at the SAME company for one person — unusual but legal.
    _onboard(client, north, "Arjun Das", rider_id="SF-1B", person_id=a["person_id"])

    s = client.get("/api/app/my-recruiting", headers=north).json()
    assert s["counts"]["all_time"] == 1
    by_company = {x["company_name"]: x["riders"] for x in s["by_company"]}
    assert by_company == {"Shadowfax": 1, "Kaptan": 1}, "one person, counted once per company"


def test_retention_denominator_is_people(db, client):
    """still_working / all_time is a percentage of people. Counting one
    person's two ids in the denominator quietly halved every retention figure
    for anybody working two companies."""
    boss = _hdr(client, "boss@t.test", "Creator-pass-1")
    north = _hdr(client, "north@t.test", "Recruit-pass-1")
    a = _onboard(client, north, "Arjun Das", rider_id="SF-1")
    _onboard(client, north, "Arjun Das", company="Kaptan", rider_id="K-1", person_id=a["person_id"])
    # Kaptan, not Shadowfax: "worked" means a company that sends us a
    # PAYSHEET paid them (domain/worked.py), and Shadowfax is per_order — we
    # never see whether its riders rode. Paying against the SECOND id also
    # shows the count is per person: activity at either company counts once.
    db.execute("UPDATE companies SET payment_model='payout_file' WHERE company_name='Kaptan'")
    db.execute(
        "INSERT INTO transactions "
        "  (person_id, company, event_type, amount, balance_after, cycle_start, cycle_end) "
        "VALUES (?, 'Kaptan', 'PAYOUT', 100000, 100000, date('now','-3 day'), date('now'))",
        (a["person_id"],),
    )
    db.commit()
    console = next(
        r
        for r in client.get("/api/recruiters", headers=boss).json()["recruiters"]
        if r["email"] == "north@t.test"
    )
    assert (console["onboarded_all_time"], console["still_working"]) == (1, 1)
    assert console["retention_pct"] == 100.0
