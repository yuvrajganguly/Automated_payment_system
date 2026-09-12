"""Merging two people (POST /api/persons/link).

The office hit a bare HTTP 500 merging Banti Das into Shyamsundar Das on
2026-09-11. The cause was not the data: ``link_riders`` re-pointed the
dependent tables from a list written out inside the function, and that list
had drifted from the schema. It covered six tables and missed five that carry
a real foreign key — ev_closeouts, ev_closeout_reports, referrals,
rider_documents, money_requests — so the final DELETE of the secondary's
person_registry row hit the constraint and raised. On SQLite that can pass
unnoticed; PostgreSQL enforces it, so it only showed up in production.

It was the second time that list had drifted (payment_lines was the first),
which is why ``db.references.PERSON_REFS`` exists and why the first test here
is about the list rather than about a merge.
"""

from __future__ import annotations

import pytest

from payout.db.references import PERSON_REFS
from payout.db.schema import SCHEMA
from tests.conftest import assign, make_ev, make_person, make_rider


def test_person_refs_covers_every_foreign_key_in_the_schema():
    """The list is the single source of truth, so it has to be complete.

    Parsed out of the schema DDL rather than hand-listed, which is the whole
    point: add a table with a person foreign key and forget PERSON_REFS, and
    this fails here instead of as a 500 in front of somebody.
    """
    declared: set[tuple[str, str]] = set()
    table = None
    for line in SCHEMA.splitlines():
        stripped = line.strip()
        if stripped.upper().startswith("CREATE TABLE"):
            table = stripped.split()[-2] if stripped.endswith("(") else stripped.split()[-1]
            table = table.strip("(")
        if "REFERENCES person_registry" in stripped and table:
            declared.add((table, stripped.split()[0]))
    assert declared, "parsed no foreign keys — the DDL shape changed, fix this test"
    missing = declared - set(PERSON_REFS)
    assert not missing, (
        f"tables with a person_registry foreign key that PERSON_REFS does not list: "
        f"{sorted(missing)}. A merge or a delete will hit the constraint and 500."
    )
    # …and nothing listed that no longer exists, which would make every merge
    # raise "no such table" instead.
    stale = {t for t, _ in PERSON_REFS} - {t for t, _ in declared}
    assert not stale, f"PERSON_REFS lists tables with no person foreign key: {sorted(stale)}"


@pytest.fixture
def client(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("boss@t.test", hash_password("Creator-pass-1"), "creator"),
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        r = c.post(
            "/api/auth/login", data={"username": "boss@t.test", "password": "Creator-pass-1"}
        )
        assert r.status_code == 200, r.text
        c.headers["Authorization"] = "Bearer " + r.json()["access_token"]
        yield c


def _merge(client, primary, secondary):
    return client.post(
        "/api/persons/link",
        json={"primary_person_id": primary, "secondary_person_id": secondary},
    )


def _photo(db, pid, key):
    db.execute(
        "INSERT INTO rider_documents (person_id, doc_type, filename, content_type, "
        "  size_bytes, storage_key, uploaded_by) "
        "VALUES (?, 'photo', 'face.jpg', 'image/jpeg', 1024, ?, 'rec@t.test')",
        (pid, key),
    )


def _money_request(db, pid):
    db.execute(
        "INSERT INTO money_requests (created_by, person_id, direction, amount, reason) "
        "VALUES ('rec@t.test', ?, 'credit', 50000, 'fuel')",
        (pid,),
    )


def test_the_merge_that_500d(db, client):
    """Shyamsundar Das's shape exactly: an EV, a photo, a money request and
    arrears on the secondary. Every one of those tables was missing from the
    old list; any single one of them was enough to break the merge."""
    keep = make_person(db, "Banti Das", balance=0)
    gone = make_person(db, "Shyamsundar Das", balance=0, arrears=129500)
    make_rider(db, keep, "9123670992", "Jiffy", "Banti Das")
    make_rider(db, gone, "QSPEND0001", "Kaptan", "Shyamsundar Das")
    assign(db, gone, make_ev(db, "CBICEVD0135"), handover="2026-09-07")
    _photo(db, gone, "people/gone/face.jpg")
    _money_request(db, gone)
    db.commit()

    r = _merge(client, keep, gone)
    assert r.status_code == 200, r.text
    assert r.json()["merged"] is True

    # The secondary is gone, and nothing anywhere still points at them.
    assert db.execute("SELECT 1 FROM person_registry WHERE person_id=?", (gone,)).fetchone() is None
    for table, col in PERSON_REFS:
        left = db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {col}=?",  # noqa: S608 - literals
            (gone,),
        ).fetchone()[0]
        assert left == 0, f"{table}.{col} still references the merged-away person"

    # The things worth keeping came across.
    assert db.execute("SELECT person_id FROM rider_documents").fetchone()["person_id"] == keep, (
        "the photo followed the person"
    )
    assert db.execute("SELECT person_id FROM money_requests").fetchone()["person_id"] == keep
    assert {
        r["rider_id"]
        for r in db.execute("SELECT rider_id FROM rider_master WHERE person_id=?", (keep,))
    } == {"9123670992", "QSPEND0001"}
    assert (
        db.execute("SELECT outstanding FROM ev_arrears WHERE person_id=?", (keep,)).fetchone()[
            "outstanding"
        ]
        == 129500
    ), "arrears summed into the primary rather than vanishing with the row"
    assert (
        db.execute("SELECT person_id FROM ev_assignments WHERE ev_id='CBICEVD0135'").fetchone()[
            "person_id"
        ]
        == keep
    )


def test_both_holding_an_ev_closes_the_secondarys(db, client):
    """One open assignment per person is a UNIQUE constraint, so the
    secondary's has to be closed before it can move."""
    keep = make_person(db, "Keeper")
    gone = make_person(db, "Merged")
    make_rider(db, keep, "K-1", "Kaptan")
    make_rider(db, gone, "K-2", "Kaptan")
    assign(db, keep, make_ev(db, "EV-KEEP"), handover="2026-08-01")
    assign(db, gone, make_ev(db, "EV-GONE"), handover="2026-08-05")
    db.commit()

    assert _merge(client, keep, gone).status_code == 200
    rows = {
        r["ev_id"]: r["returned_date"]
        for r in db.execute(
            "SELECT ev_id, returned_date FROM ev_assignments WHERE person_id=?", (keep,)
        )
    }
    assert rows["EV-KEEP"] is None, "the primary keeps theirs open"
    assert rows["EV-GONE"] is not None, "the secondary's was closed, not dropped"


def test_both_referred_keeps_the_primarys_referral(db, client):
    """referrals.new_person_id is UNIQUE — a person cannot have been referred
    twice, so one row has to go. The money is in `transactions`, which
    survives, so what is dropped is bookkeeping and it is logged."""
    referrer = make_person(db, "Referrer")
    keep = make_person(db, "Keeper")
    gone = make_person(db, "Merged")
    for pid in (keep, gone):
        make_rider(db, pid, f"K-{pid}", "Kaptan")
        db.execute(
            "INSERT INTO referrals (new_person_id, referrer_person_id, company, "
            "  installments_paid) VALUES (?, ?, 'Kaptan', 1)",
            (pid, referrer),
        )
    db.commit()

    r = _merge(client, keep, gone)
    assert r.status_code == 200, r.text
    rows = db.execute("SELECT new_person_id FROM referrals").fetchall()
    assert [x["new_person_id"] for x in rows] == [keep]
    feed = db.execute(
        "SELECT details FROM activity_log WHERE action='person.merge' ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert "dropped_referral" in (feed["details"] or ""), "a dropped referral must be recorded"


def test_merging_a_referrer_into_their_referee_voids_the_referral(db, client):
    """Otherwise the merged person has referred themselves, and would qualify
    for the bonus."""
    keep = make_person(db, "Referee")
    gone = make_person(db, "Referrer")
    make_rider(db, keep, "K-1", "Kaptan")
    make_rider(db, gone, "K-2", "Kaptan")
    db.execute(
        "INSERT INTO referrals (new_person_id, referrer_person_id, company) "
        "VALUES (?, ?, 'Kaptan')",
        (keep, gone),
    )
    db.commit()

    assert _merge(client, keep, gone).status_code == 200
    row = db.execute("SELECT status, note, referrer_person_id FROM referrals").fetchone()
    assert row["referrer_person_id"] == keep
    assert row["status"] == "void"
    assert "same person" in (row["note"] or "")


def test_an_unrelated_self_referral_is_left_alone(db, client):
    """The void is scoped to the merged person. Somebody else's odd row is not
    this merge's to rewrite."""
    stranger = make_person(db, "Stranger")
    db.execute(
        "INSERT INTO referrals (new_person_id, referrer_person_id, company) "
        "VALUES (?, ?, 'Kaptan')",
        (stranger, stranger),
    )
    keep = make_person(db, "Keeper")
    gone = make_person(db, "Merged")
    make_rider(db, keep, "K-1", "Kaptan")
    make_rider(db, gone, "K-2", "Kaptan")
    db.commit()

    assert _merge(client, keep, gone).status_code == 200
    row = db.execute("SELECT status FROM referrals WHERE new_person_id=?", (stranger,)).fetchone()
    assert row["status"] == "open"


def test_merging_somebody_into_themselves_is_a_no_op(db, client):
    pid = make_person(db, "Only One")
    make_rider(db, pid, "K-1", "Kaptan")
    db.commit()
    r = _merge(client, pid, pid)
    assert r.status_code == 200 and r.json()["merged"] is False
    assert db.execute("SELECT 1 FROM person_registry WHERE person_id=?", (pid,)).fetchone()
