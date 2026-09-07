"""Recruiter app, round two: who onboarded whom, hub zones, fleet filters,
recruiting numbers and the Level-1 location stamp on actions."""

from __future__ import annotations

import pytest

from tests.conftest import assign, make_ev, make_person, make_rider


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
            ("rec2@t.test", hash_password("Recruit-pass-2"), "recruiter"),
            ("boss@t.test", hash_password("Creator-pass-1"), "creator"),
        ],
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        yield c


def _hdr(client, email="rec@t.test", pw="Recruit-pass-1", **extra):
    r = client.post(
        "/api/auth/login", data={"username": email, "password": pw, "device": "android"}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"], **extra}


def _onboard(client, hdr, name, company="Shadowfax", rider_id=None, hub=None, person_id=None):
    body = {"company": company, "name": name, "hub": hub, "person_id": person_id}
    if rider_id:
        body["rider_id"] = rider_id
    r = client.post("/api/riders", json=body, headers=hdr)
    assert r.status_code in (200, 201), r.text
    return r.json()


def test_onboarding_stamps_recruiter_and_location(db, client):
    hdr = _hdr(client, **{"X-Client-Location": "22.5726,88.3639,12.5"})
    out = _onboard(client, hdr, "Arjun Das", rider_id="SF-1", hub="Salt Lake")
    assert out["recruited_by"] == "rec@t.test"
    row = db.execute(
        "SELECT recruited_by FROM rider_master WHERE rider_id='SF-1' AND company='Shadowfax'"
    ).fetchone()
    assert row["recruited_by"] == "rec@t.test"
    act = db.execute(
        "SELECT lat, lng, accuracy_m FROM activity_log WHERE action='rider.create' "
        "ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert (act["lat"], act["lng"]) == (22.5726, 88.3639) and act["accuracy_m"] == 12.5

    # Web console (no header) leaves the location empty; garbage is ignored, not a 400.
    _onboard(client, _hdr(client), "Bikash Roy", rider_id="SF-2")
    act = db.execute(
        "SELECT lat, lng FROM activity_log WHERE action='rider.create' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert act["lat"] is None and act["lng"] is None
    _onboard(
        client, _hdr(client, **{"X-Client-Location": "not,a,location"}), "C Sen", rider_id="SF-3"
    )
    act = db.execute(
        "SELECT lat FROM activity_log WHERE action='rider.create' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert act["lat"] is None
    # Out-of-range coordinates are dropped too.
    _onboard(client, _hdr(client, **{"X-Client-Location": "95,200"}), "D Sen", rider_id="SF-4")
    act = db.execute(
        "SELECT lat FROM activity_log WHERE action='rider.create' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert act["lat"] is None


def test_my_riders_and_recruited_by_is_admin_only(db, client):
    rec, rec2 = _hdr(client), _hdr(client, "rec2@t.test", "Recruit-pass-2")
    boss = _hdr(client, "boss@t.test", "Creator-pass-1")
    _onboard(client, rec, "Arjun Das", rider_id="SF-1")
    _onboard(client, rec, "Bikash Roy", rider_id="SF-2")
    _onboard(client, rec2, "Chandan Sen", rider_id="SF-3")
    # A legacy rider nobody is credited for.
    make_rider(db, make_person(db, "Old Timer"), "SF-9", "Shadowfax", "Old Timer")
    db.commit()

    mine = client.get("/api/riders?mine=1", headers=rec).json()
    assert sorted(r["rider_id"] for r in mine) == ["SF-1", "SF-2"]
    assert client.get("/api/riders?mine=1", headers=rec2).json()[0]["rider_id"] == "SF-3"
    everyone = client.get("/api/riders", headers=rec)
    assert everyone.headers["X-Total-Count"] == "4"
    # Admin can look at any recruiter's riders by email.
    byrec = client.get("/api/riders?recruited_by=REC2@t.test", headers=boss).json()
    assert [r["rider_id"] for r in byrec] == ["SF-3"]

    # Re-crediting a rider is an admin action.
    r = client.patch(
        "/api/riders/SF-9?company=Shadowfax", json={"recruited_by": "rec@t.test"}, headers=rec
    )
    assert r.status_code == 403, r.text
    r = client.patch(
        "/api/riders/SF-9?company=Shadowfax", json={"recruited_by": "rec@t.test"}, headers=boss
    )
    assert r.status_code == 200, r.text
    assert r.json()["recruited_by"] == "rec@t.test"
    assert client.get("/api/riders?mine=1", headers=rec).headers["X-Total-Count"] == "3"


def test_hub_zones_filter_riders_and_fleet(db, client):
    rec = _hdr(client)
    boss = _hdr(client, "boss@t.test", "Creator-pass-1")
    p1 = make_person(db, "Arjun Das")
    make_rider(db, p1, "SF-1", "Shadowfax", "Arjun Das")
    p2 = make_person(db, "Bikash Roy")
    make_rider(db, p2, "SF-2", "Shadowfax", "Bikash Roy")
    p3 = make_person(db, "Chandan Sen")
    make_rider(db, p3, "SF-3", "Shadowfax", "Chandan Sen")
    db.execute("UPDATE rider_master SET hub='Salt Lake' WHERE rider_id='SF-1'")
    db.execute("UPDATE rider_master SET hub='Garia' WHERE rider_id='SF-2'")
    db.execute("UPDATE rider_master SET hub='Howrah' WHERE rider_id='SF-3'")
    assign(db, p1, make_ev(db, "EV-N"), handover="2026-08-01")
    assign(db, p2, make_ev(db, "EV-S"), handover="2026-08-01")
    make_ev(db, "EV-SPARE")
    db.commit()

    # Stores are listed per company even before any zone is set; unassigned first.
    hubs = client.get("/api/hubs?company=Shadowfax", headers=rec).json()
    assert [h["hub"] for h in hubs] == ["Garia", "Howrah", "Salt Lake"]
    assert all(h["zone"] is None and h["company"] == "Shadowfax" for h in hubs)
    assert {h["hub"]: (h["riders"], h["evs"]) for h in hubs}["Salt Lake"] == (1, 1)
    assert hubs[0]["payment_model"] == "per_order"

    # Recruiters cannot classify; admins can, and any spelling of the zone works.
    put = lambda hub, body, h: client.put(f"/api/hubs/Shadowfax/{hub}", json=body, headers=h)  # noqa: E731
    assert put("Garia", {"zone": "South"}, rec).status_code == 403
    assert put("Salt Lake", {"zone": "north"}, boss).status_code == 200
    assert put("Garia", {"zone": "South"}, boss).status_code == 200
    assert put("Garia", {"zone": "East"}, boss).status_code == 400
    assert put("Garia", {"zone": "misc"}, boss).json()["zone"] == "Misc"
    assert put("Garia", {"zone": "South"}, boss).status_code == 200
    # A store with no riders yet can be classified ahead of time; unknown company → 404.
    assert put("New Town", {"zone": "North"}, boss).status_code == 200
    assert client.put("/api/hubs/Nope/X", json={"zone": "North"}, headers=boss).status_code == 404
    hubs = {
        h["hub"]: h["zone"] for h in client.get("/api/hubs?company=Shadowfax", headers=rec).json()
    }
    assert hubs == {"Salt Lake": "North", "Garia": "South", "Howrah": None, "New Town": "North"}
    assert (
        db.execute("SELECT COUNT(*) FROM activity_log WHERE action='hub.update'").fetchone()[0] == 5
    )
    # Store-level pay for a per-order company, rupees in and out.
    r = put("Salt Lake", {"per_order_rate": 18, "notes": "busy store"}, boss).json()
    assert r["per_order_rate"] == 18.0 and r["zone"] == "North" and r["notes"] == "busy store"
    assert put("Salt Lake", {"per_order_rate": -1}, boss).status_code == 400

    north = client.get("/api/riders?zone=north", headers=rec)
    assert [r["rider_id"] for r in north.json()] == ["SF-1"] and north.headers[
        "X-Total-Count"
    ] == "1"
    assert north.json()[0]["zone"] == "North"
    south = client.get("/api/riders?zone=South", headers=rec).json()
    assert [r["rider_id"] for r in south] == ["SF-2"]
    assert client.get("/api/riders?zone=West", headers=rec).status_code == 400
    # Howrah has no zone → not in either bucket, but still in the full list.
    assert client.get("/api/riders", headers=rec).headers["X-Total-Count"] == "3"

    evs_n = client.get("/api/evs?zone=North", headers=rec).json()
    assert [e["ev_id"] for e in evs_n] == ["EV-N"] and evs_n[0]["zone"] == "North"
    assert [e["ev_id"] for e in client.get("/api/evs?zone=South", headers=rec).json()] == ["EV-S"]
    assert len(client.get("/api/evs", headers=rec).json()) == 3

    # Bootstrap carries the zone map so the app can label hubs offline.
    b = client.get("/api/app/bootstrap", headers=rec).json()
    assert b["hub_zones"]["Salt Lake"] == "North" and b["hub_zones"]["Howrah"] is None
    assert "New Town" in b["hubs"] and b["zones"] == ["North", "South", "Misc"]
    assert {"company": "Shadowfax", "hub": "New Town", "zone": "North"} in b["company_hubs"]

    # Clearing a zone.
    assert put("Garia", {"zone": None}, boss).status_code == 200
    assert client.get("/api/riders?zone=South", headers=rec).json() == []


def test_my_fleet_follows_my_riders(db, client):
    rec, rec2 = _hdr(client), _hdr(client, "rec2@t.test", "Recruit-pass-2")
    a = _onboard(client, rec, "Arjun Das", rider_id="SF-1")
    b = _onboard(client, rec2, "Bikash Roy", rider_id="SF-2")
    assign(db, a["person_id"], make_ev(db, "EV-A"), handover="2026-08-01")
    assign(db, b["person_id"], make_ev(db, "EV-B"), handover="2026-08-01")
    make_ev(db, "EV-C")
    db.commit()
    mine = client.get("/api/evs?mine=1", headers=rec).json()
    assert [e["ev_id"] for e in mine] == ["EV-A"] and mine[0]["recruited_by"] == "rec@t.test"
    assert mine[0]["holder_active"] is True and mine[0]["total_dues"] == 0
    # Holder goes inactive and owes: the fleet row says so (the app's Dues / Inactive views).
    db.execute("UPDATE rider_master SET is_active=0 WHERE rider_id='SF-1'")
    db.execute("UPDATE balances SET current_balance=-20000 WHERE person_id=?", (a["person_id"],))
    db.commit()
    mine = client.get("/api/evs?mine=1", headers=rec).json()
    assert mine[0]["holder_active"] is False and mine[0]["total_dues"] == 200.0
    spare = next(e for e in client.get("/api/evs", headers=rec).json() if e["ev_id"] == "EV-C")
    assert spare["holder_active"] is None and spare["total_dues"] is None
    assert [e["ev_id"] for e in client.get("/api/evs?mine=1", headers=rec2).json()] == ["EV-B"]
    # Spare units belong to nobody, so "my fleet" never shows them.
    assert "EV-C" not in {e["ev_id"] for e in mine}


def test_recruiting_numbers(db, client):
    rec, rec2 = _hdr(client), _hdr(client, "rec2@t.test", "Recruit-pass-2")
    boss = _hdr(client, "boss@t.test", "Creator-pass-1")
    a = _onboard(client, rec, "Arjun Das", rider_id="SF-1")
    # Same person given a second company id: two onboardings, one person.
    _onboard(client, rec, "Arjun Das", company="Blitz", rider_id="31111", person_id=a["person_id"])
    _onboard(client, rec, "Bikash Roy", rider_id="SF-2")
    _onboard(client, rec2, "Chandan Sen", rider_id="SF-3")
    # One of rec's riders was onboarded long ago and has since left.
    db.execute(
        "UPDATE rider_master SET created_at='2025-01-05 10:00:00', is_active=0 "
        "WHERE rider_id='SF-2'"
    )
    assign(db, a["person_id"], make_ev(db, "EV-A"), handover="2026-08-01")
    db.commit()

    s = client.get("/api/app/my-recruiting", headers=rec).json()
    assert s["email"] == "rec@t.test"
    c = s["counts"]
    assert c["all_time"] == 3 and c["persons"] == 2 and c["active"] == 2 and c["ev_holders"] == 1
    assert c["today"] == 2 and c["week"] == 2 and c["month"] == 2
    assert [(x["company_name"], x["riders"]) for x in s["by_company"]] == [
        ("Shadowfax", 2),
        ("Blitz", 1),
    ]
    assert s["recent"][0]["rider_id"] in ("SF-1", "31111") and s["recent"][-1]["rider_id"] == "SF-2"
    assert "amount" not in str(s) and "balance" not in str(s)

    # Only admins look at somebody else; the board lists everyone for them.
    r = client.get("/api/app/my-recruiting?email=rec2@t.test", headers=rec)
    assert r.status_code == 403
    other = client.get("/api/app/my-recruiting?email=REC2@t.test", headers=boss).json()
    assert other["email"] == "rec2@t.test" and other["counts"]["all_time"] == 1
    board = client.get("/api/app/recruiting", headers=boss).json()["recruiters"]
    assert [(b["email"], b["all_time"], b["month"]) for b in board] == [
        ("rec@t.test", 3, 2),
        ("rec2@t.test", 1, 1),
    ]
    board = client.get("/api/app/recruiting", headers=rec2).json()["recruiters"]
    assert [b["email"] for b in board] == ["rec2@t.test"]


def test_migration_backfills_recruited_by_from_activity(db):
    """Riders created before 0018 get credited from the activity log."""
    from payout.db.migrations import _0018_recruiter_app_fields

    p = make_person(db, "Arjun Das")
    make_rider(db, p, "SF-1", "Shadowfax", "Arjun Das")
    make_rider(db, p, "31111", "Blitz", "Arjun Das")
    db.execute(
        "INSERT INTO activity_log (email, role, action, entity_type, entity_id) "
        "VALUES ('rec@t.test','recruiter','rider.create','rider','SF-1@Shadowfax')"
    )
    db.commit()
    _0018_recruiter_app_fields(db)
    db.commit()
    rows = {
        r["rider_id"]: r["recruited_by"]
        for r in db.execute("SELECT rider_id, recruited_by FROM rider_master")
    }
    assert rows == {"SF-1": "rec@t.test", "31111": None}


def test_todo_groups_store_visits_by_zone(db, client):
    """COD to collect, EV holders with dues, EVs to pick up from inactive
    riders — grouped by store, filtered to the recruiter's zone."""
    rec = _hdr(client)
    boss = _hdr(client, "boss@t.test", "Creator-pass-1")

    # Salt Lake (North): Arjun holds COD; Bikash holds an EV and owes rent.
    p_arjun = make_person(db, "Arjun Das")
    make_rider(db, p_arjun, "SF-1", "Shadowfax", "Arjun Das")
    db.execute(
        "INSERT INTO ev_arrears (person_id, cod_missed, cod_outstanding) VALUES (?, 50000, 50000)",
        (p_arjun,),
    )
    p_bikash = make_person(db, "Bikash Roy", balance=-20000, arrears=125000)
    make_rider(db, p_bikash, "SF-2", "Shadowfax", "Bikash Roy")
    assign(db, p_bikash, make_ev(db, "EV-B"), handover="2026-08-01")
    # Garia (South): Chandan left but still has the unit.
    p_chandan = make_person(db, "Chandan Sen")
    make_rider(db, p_chandan, "SF-3", "Shadowfax", "Chandan Sen")
    assign(db, p_chandan, make_ev(db, "EV-C"), handover="2026-06-01")
    db.execute("UPDATE rider_master SET is_active=0 WHERE rider_id='SF-3'")
    # Howrah (no zone yet): Dipak has a small COD balance. Eshan is clean.
    p_dipak = make_person(db, "Dipak Roy")
    make_rider(db, p_dipak, "SF-4", "Shadowfax", "Dipak Roy")
    db.execute(
        "INSERT INTO ev_arrears (person_id, cod_missed, cod_outstanding) VALUES (?, 1000, 1000)",
        (p_dipak,),
    )
    p_eshan = make_person(db, "Eshan Pal", balance=5000)
    make_rider(db, p_eshan, "SF-5", "Shadowfax", "Eshan Pal")
    assign(db, p_eshan, make_ev(db, "EV-E"), handover="2026-08-01")
    for rid, hub in [("SF-1", "Salt Lake"), ("SF-2", "Salt Lake"), ("SF-3", "Garia")]:
        db.execute("UPDATE rider_master SET hub=? WHERE rider_id=?", (hub, rid))
    db.execute("UPDATE rider_master SET hub='Howrah' WHERE rider_id IN ('SF-4','SF-5')")
    db.commit()
    client.put("/api/hubs/Shadowfax/Salt Lake", json={"zone": "North"}, headers=boss)
    client.put("/api/hubs/Shadowfax/Garia", json={"zone": "South"}, headers=boss)

    # No zone on the account yet → everything, labelled by store.
    t = client.get("/api/app/todo", headers=rec).json()
    assert t["zone"] == "all" and t["my_zone"] is None
    assert t["counts"] == {
        "cod_items": 2,
        "ev_dues_items": 1,
        "inactive_ev_items": 1,
        "total": 4,
        "stores": 3,
    }
    assert [s["hub"] for s in t["stores"]] == ["Salt Lake", "Garia", "Howrah"]
    salt = t["stores"][0]
    assert salt["zone"] == "North"
    kinds = {(i["kind"], i["name"]) for i in salt["items"]}
    assert kinds == {("cod", "Arjun Das"), ("ev_dues", "Bikash Roy")}
    cod = next(i for i in salt["items"] if i["kind"] == "cod")
    assert cod["cod_outstanding"] == 500.0 and cod["title"] == "Collect COD · Arjun Das"
    dues = next(i for i in salt["items"] if i["kind"] == "ev_dues")
    assert dues["ev_id"] == "EV-B" and dues["total_dues"] == 1450.0
    assert dues["outstanding"] == 1250.0 and dues["dues_outstanding"] == 200.0
    garia = t["stores"][1]["items"][0]
    assert garia["kind"] == "inactive_ev" and garia["ev_id"] == "EV-C"
    assert garia["title"] == "Collect EV-C · Chandan Sen is inactive"
    assert "Eshan" not in str(t)  # clean rider, nothing to do

    # Zone on the account narrows it; admins can set it, recruiters cannot.
    r = client.patch("/api/users/rec@t.test/zone", json={"zone": "north"}, headers=rec)
    assert r.status_code == 403
    r = client.patch("/api/users/rec@t.test/zone", json={"zone": "north"}, headers=boss)
    assert r.status_code == 200 and r.json()["zone"] == "North"
    assert (
        client.patch("/api/users/rec@t.test/zone", json={"zone": "East"}, headers=boss).status_code
        == 400
    )
    me = client.get("/api/app/bootstrap", headers=rec).json()["me"]
    assert me["zone"] == "North"
    t = client.get("/api/app/todo", headers=rec).json()
    assert t["zone"] == "North" and t["my_zone"] == "North"
    assert [s["hub"] for s in t["stores"]] == ["Salt Lake"] and t["counts"]["total"] == 2
    # …but a recruiter can still look at the other zone, or everything.
    assert [
        s["hub"] for s in client.get("/api/app/todo?zone=South", headers=rec).json()["stores"]
    ] == ["Garia"]
    assert client.get("/api/app/todo?zone=all", headers=rec).json()["counts"]["total"] == 4
    assert [
        s["hub"] for s in client.get("/api/app/todo?zone=unassigned", headers=rec).json()["stores"]
    ] == ["Howrah"]
    assert client.get("/api/app/todo?zone=West", headers=rec).status_code == 400
    users = {u["email"]: u.get("zone") for u in client.get("/api/users", headers=boss).json()}
    assert users["rec@t.test"] == "North"


def test_location_on_app_open_is_throttled_to_30_minutes(db, client):
    rec = _hdr(client)
    boss = _hdr(client, "boss@t.test", "Creator-pass-1")
    body = {"lat": 22.5726, "lng": 88.3639, "accuracy_m": 15.0, "area": "Salt Lake, Kolkata"}
    r = client.post("/api/app/location", json=body, headers=rec)
    assert r.status_code == 200 and r.json()["recorded"] is True
    # Opening the app again five minutes later records nothing.
    r = client.post("/api/app/location", json={**body, "lat": 22.58}, headers=rec)
    assert r.json()["recorded"] is False and r.json()["next_after"]
    assert db.execute("SELECT COUNT(*) FROM recruiter_locations").fetchone()[0] == 1
    # …but after the gap it does.
    from datetime import datetime, timedelta

    earlier = (datetime.utcnow() - timedelta(minutes=31)).strftime("%Y-%m-%d %H:%M:%S")
    db.execute("UPDATE recruiter_locations SET at=?", (earlier,))
    db.commit()
    r = client.post("/api/app/location", json={**body, "lat": 22.58, "area": None}, headers=rec)
    assert r.json()["recorded"] is True
    assert (
        client.post("/api/app/location", json={"lat": 95, "lng": 0}, headers=rec).status_code == 400
    )

    mine = client.get("/api/app/locations", headers=rec).json()
    assert [m["lat"] for m in mine] == [22.58, 22.5726]
    assert mine[1]["area"] == "Salt Lake, Kolkata" and mine[1]["source"] == "app_open"
    assert client.get("/api/app/locations?email=boss@t.test", headers=rec).status_code == 403
    theirs = client.get("/api/app/locations?email=REC@t.test", headers=boss).json()
    assert len(theirs) == 2 and theirs[0]["email"] == "rec@t.test"
    assert (
        client.get("/api/app/locations?email=rec@t.test&limit=1", headers=boss).json()[0]["lat"]
        == 22.58
    )
