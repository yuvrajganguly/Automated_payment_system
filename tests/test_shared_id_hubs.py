"""A store learned from one brand's file reaches the sibling that shares its ids.

Blitz sends Kaptan and Nykaa either as two payout files or as one combined
file — separate one week, combined the next. When it arrives combined the whole
thing is processed under whichever name the operator picks, because the rider
id is the same either way.

The hub sync had no idea about that. It wrote the store onto the roster row for
the company being processed and nothing else, so a combined file filed under
Kaptan left every Nykaa row holding whatever store it had before. Same rider,
same store, two rows disagreeing — and since 2026-09 the store is what puts a
rider in a zone, so the disagreement decides which recruiter sees them.
"""

from __future__ import annotations

import io
from datetime import date

from openpyxl import Workbook

from payout.domain.engine import process_cycle
from tests.conftest import make_person, make_rider

CYCLE = (date(2026, 8, 24), date(2026, 8, 30))


def _blitz_file(rows) -> bytes:
    """Kaptan's layout: rider_id / net_pay / total_del, plus a store column."""
    wb = Workbook()
    ws = wb.active
    ws.append(["rider_id", "rider_name", "hub", "total_del", "net_pay"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _hubs(db, rider_id):
    return {
        r["company"]: r["hub"]
        for r in db.execute("SELECT company, hub FROM rider_master WHERE rider_id=?", (rider_id,))
    }


def test_a_combined_file_moves_the_hub_on_both_brands(db):
    p = make_person(db, "Somnath Sardar")
    make_rider(db, p, "31111", "Kaptan", "Somnath Sardar")
    make_rider(db, p, "31111", "Nykaa", "Somnath Sardar")
    db.execute("UPDATE rider_master SET hub='Old Store' WHERE rider_id='31111'")
    db.commit()

    data = _blitz_file([["31111", "Somnath Sardar", "Nykaa Salt Lake", 40, 3000]])
    r = process_cycle("Kaptan", *CYCLE, data, commit=True)
    assert r.committed, r.errors

    # Both rows, one store. Nykaa's row was never in the file being processed.
    assert _hubs(db, "31111") == {"Kaptan": "Nykaa Salt Lake", "Nykaa": "Nykaa Salt Lake"}
    assert sorted((u["company"], u["new_hub"]) for u in r.hub_updates) == [
        ("Kaptan", "Nykaa Salt Lake"),
        ("Nykaa", "Nykaa Salt Lake"),
    ]


def test_it_travels_the_other_way_too(db):
    """rider_ids_shared_with points one way — Nykaa names Kaptan — but a shared
    id space is symmetric: 31111 is the same rider whichever brand sent it."""
    p = make_person(db, "Somnath Sardar")
    make_rider(db, p, "31111", "Kaptan", "Somnath Sardar")
    make_rider(db, p, "31111", "Nykaa", "Somnath Sardar")
    db.execute("UPDATE rider_master SET hub='Old Store' WHERE rider_id='31111'")
    db.commit()

    data = _blitz_file([["31111", "Somnath Sardar", "Kaptan Garia", 40, 3000]])
    r = process_cycle("Nykaa", *CYCLE, data, commit=True)
    assert r.committed, r.errors
    assert _hubs(db, "31111") == {"Kaptan": "Kaptan Garia", "Nykaa": "Kaptan Garia"}


def test_an_unrelated_company_keeps_its_own_store(db):
    """A rider's store at Shadowfax is a different place from their store at
    Kaptan. The hub stops at the id-sharing pair."""
    p = make_person(db, "Two brands")
    make_rider(db, p, "31111", "Kaptan", "Two brands")
    make_rider(db, p, "31111", "Shadowfax", "Two brands")
    db.execute("UPDATE rider_master SET hub='Old Store' WHERE rider_id='31111'")
    db.commit()

    data = _blitz_file([["31111", "Two brands", "Nykaa Salt Lake", 40, 3000]])
    r = process_cycle("Kaptan", *CYCLE, data, commit=True)
    assert r.committed, r.errors
    assert _hubs(db, "31111") == {"Kaptan": "Nykaa Salt Lake", "Shadowfax": "Old Store"}


def test_the_same_id_belonging_to_a_different_person_is_left_alone(db):
    """The id space is meant to be shared, but a collision must not move
    somebody else's store — and since the store decides the zone, it would
    move them to another recruiter's list."""
    mine = make_person(db, "Somnath Sardar")
    theirs = make_person(db, "Somebody Else")
    make_rider(db, mine, "31111", "Kaptan", "Somnath Sardar")
    make_rider(db, theirs, "31111", "Nykaa", "Somebody Else")
    db.execute("UPDATE rider_master SET hub='Old Store' WHERE rider_id='31111'")
    db.commit()

    data = _blitz_file([["31111", "Somnath Sardar", "Nykaa Salt Lake", 40, 3000]])
    r = process_cycle("Kaptan", *CYCLE, data, commit=True)
    assert r.committed, r.errors
    assert _hubs(db, "31111") == {"Kaptan": "Nykaa Salt Lake", "Nykaa": "Old Store"}


def test_a_dry_run_still_writes_nothing(db):
    p = make_person(db, "Somnath Sardar")
    make_rider(db, p, "31111", "Kaptan", "Somnath Sardar")
    make_rider(db, p, "31111", "Nykaa", "Somnath Sardar")
    db.execute("UPDATE rider_master SET hub='Old Store' WHERE rider_id='31111'")
    db.commit()

    data = _blitz_file([["31111", "Somnath Sardar", "Nykaa Salt Lake", 40, 3000]])
    process_cycle("Kaptan", *CYCLE, data, commit=False)
    assert _hubs(db, "31111") == {"Kaptan": "Old Store", "Nykaa": "Old Store"}
