"""A field you can write but cannot read back (2026-09-24).

Recruiters reported adding a bank account and a phone number in the app and
finding them gone later. Nothing was ever lost. `PATCH /riders/{id}` wrote the
columns, `GET /riders` returned them — and `GET /persons/{id}`, which is the
screen the app shows straight after an edit, did not select `account_name` or
`recruited_by` at all. The app folds what it reads into its local cache, so the
holder name it had just saved came back blank and stayed blank.

This is the third time this list has drifted, always the same way and always
invisible: writable through one route, missing from a SELECT that feeds the
same response model. So there is now one column list and this test, which
fails when a route builds a RiderOut from a narrower one.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from payout.api import ratelimit  # noqa: E402
from payout.api.app import app  # noqa: E402
from payout.api.routes.riders import RIDER_OUT_SQL  # noqa: E402
from payout.api.schemas import RiderOut  # noqa: E402
from payout.auth import hash_password  # noqa: E402

# Fields of RiderOut that do not come from a rider_master column: they are
# derived, joined, or only ever set by the route that returns them.
_NOT_COLUMNS = {
    "vehicle",  # derived from whether an EV assignment is open
    "zone",  # joined from company_hubs
    "working",  # computed by domain/worked.py
    "last_worked_on",
    "referred_by",
    "copied_from",
}


def test_every_rider_out_column_is_in_the_shared_select():
    missing = [
        f
        for f in RiderOut.model_fields
        if f not in _NOT_COLUMNS
        and f"rm.{f}" not in RIDER_OUT_SQL
        and f" AS {f}" not in RIDER_OUT_SQL
    ]
    assert not missing, (
        f"RiderOut declares {missing} but RIDER_OUT_SQL does not select them — "
        f"they will be writable and come back blank."
    )


@pytest.fixture
def client(db):
    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active, zone) "
        "VALUES ('rec@t.test', ?, 'recruiter', 1, 'North')",
        (hash_password("Recruit-pass-1"),),
    )
    db.execute("INSERT INTO company_hubs (company, hub, zone) VALUES ('Jiffy','Salt Lake','North')")
    db.commit()
    ratelimit.reset()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _login(client):
    r = client.post(
        "/api/auth/login", data={"username": "rec@t.test", "password": "Recruit-pass-1"}
    )
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def test_a_bank_detail_saved_from_the_app_reads_back_on_the_person_screen(client):
    """The exact round trip a recruiter makes: onboard, edit, look again."""
    h = _login(client)
    made = client.post(
        "/api/riders",
        json={
            "company": "Jiffy",
            "name": "Probe One",
            "hub": "Salt Lake",
            "account_no": "1234567890",
            "ifsc": "SBIN0001",
            "mob_no": "9000000001",
        },
        headers=h,
    )
    assert made.status_code == 201, made.text
    rid, pid = made.json()["rider_id"], made.json()["person_id"]

    edit = client.patch(
        f"/api/riders/{rid}?company=Jiffy",
        json={"account_no": "9999999999", "mob_no": "9000000002", "account_name": "Wife"},
        headers=h,
    )
    assert edit.status_code == 200, edit.text

    row = client.get(f"/api/persons/{pid}", headers=h).json()["riders"][0]
    assert row["account_no"] == "9999999999"
    assert row["mob_no"] == "9000000002"
    assert row["account_name"] == "Wife", "the holder name saved but the person screen lost it"
    assert row["recruited_by"] == "rec@t.test"


def test_the_three_routes_agree_on_one_rider(client):
    """PATCH's response, the riders list and the person screen are three
    different SELECTs feeding one model. They have to say the same thing."""
    h = _login(client)
    made = client.post(
        "/api/riders",
        json={
            "company": "Jiffy",
            "name": "Probe Two",
            "hub": "Salt Lake",
            "account_no": "1111111111",
            "account_name": "Father",
            "ifsc": "SBIN0002",
            "mob_no": "9000000003",
        },
        headers=h,
    )
    rid, pid = made.json()["rider_id"], made.json()["person_id"]

    patched = client.patch(
        f"/api/riders/{rid}?company=Jiffy", json={"hub": "Salt Lake"}, headers=h
    ).json()
    listed = [
        r for r in client.get("/api/riders?company=Jiffy", headers=h).json() if r["rider_id"] == rid
    ][0]
    on_person = client.get(f"/api/persons/{pid}", headers=h).json()["riders"][0]

    for field in ("account_no", "account_name", "ifsc", "mob_no", "recruited_by"):
        assert patched[field] == listed[field] == on_person[field], (
            f"{field} differs between the three routes: "
            f"{patched[field]!r} / {listed[field]!r} / {on_person[field]!r}"
        )
