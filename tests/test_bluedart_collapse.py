"""Migration 0006 — the retired Blue Dart module folds into the central model.

The bluedart_* tables only exist in databases that once ran the Blue Dart
branch, so the test creates them by hand, seeds a small roster, and asserts
the collapse: active riders get rider_master rows under 'BlueDart', their
open EV holdings become ev_assignments with the rent meter at 2026-08-31
(billing starts 1 Sept), conflicts are skipped, and fresh databases no-op.
"""

from __future__ import annotations

from payout.config import DB_URL
from payout.db.migrations import run_migrations
from tests.conftest import assign, make_ev, make_person

_BD_DDL = [
    """CREATE TABLE bluedart_stores (
        store_code TEXT PRIMARY KEY, name TEXT, address TEXT, pincode TEXT,
        is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT)""",
    """CREATE TABLE bluedart_riders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER NOT NULL, bd_rider_id TEXT UNIQUE, name TEXT, hub TEXT,
        store_code TEXT, mob_no TEXT, account_no TEXT, ifsc TEXT,
        monthly_salary INTEGER NOT NULL DEFAULT 0, joined_date TEXT,
        is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT, updated_at TEXT)""",
    """CREATE TABLE bluedart_ev (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bd_rider_id INTEGER NOT NULL, ev_id TEXT NOT NULL,
        handover_date TEXT, returned_date TEXT, notes TEXT, created_at TEXT)""",
]


def _seed_bd(db):
    for ddl in _BD_DDL:
        if DB_URL:
            from payout.db.connection import translate_ddl

            db.executescript(translate_ddl(ddl))
        else:
            db.execute(ddl)
    db.execute("DELETE FROM schema_migrations WHERE name='0006_collapse_bluedart'")


def _run(db):
    ran = run_migrations(db, fresh_database=False)
    assert "0006_collapse_bluedart" in ran
    db.commit()


def test_active_bd_rider_and_ev_collapse(db):
    pid = make_person(db, "BD Worker")
    make_ev(db, "EV-BD1", provider="Raft", model="Regular")
    _seed_bd(db)
    db.execute(
        "INSERT INTO bluedart_riders (person_id, bd_rider_id, name, hub, joined_date, is_active) "
        "VALUES (?, 'BD001', 'BD Worker', 'BTX', '2026-03-15', 1)",
        (pid,),
    )
    db.execute(
        "INSERT INTO bluedart_ev (bd_rider_id, ev_id, handover_date) "
        "VALUES (1, 'EV-BD1', '2026-04-01')"
    )
    db.commit()
    _run(db)

    rm = db.execute(
        "SELECT * FROM rider_master WHERE rider_id='BD001' AND company='BlueDart'"
    ).fetchone()
    assert rm and rm["person_id"] == pid and rm["vehicle"] == "EV"
    pr = db.execute(
        "SELECT deduction_company, deduction_rider_id FROM person_registry WHERE person_id=?",
        (pid,),
    ).fetchone()
    assert pr["deduction_company"] == "BlueDart" and pr["deduction_rider_id"] == "BD001"
    a = db.execute(
        "SELECT * FROM ev_assignments WHERE person_id=? AND returned_date IS NULL", (pid,)
    ).fetchone()
    assert a["ev_id"] == "EV-BD1"
    assert a["handover_date"] == "2026-04-01"
    assert a["rent_charged_through"] == "2026-08-31", "rent must start 1 Sept"
    assert db.execute("SELECT status FROM ev_units WHERE ev_id='EV-BD1'").fetchone()[0] == "in_use"
    bd = db.execute("SELECT returned_date, notes FROM bluedart_ev WHERE id=1").fetchone()
    assert bd["returned_date"] == "2026-08-31" and "migrated" in bd["notes"]
    assert db.execute("SELECT 1 FROM companies WHERE company_name='BlueDart'").fetchone(), (
        "BlueDart company must exist"
    )


def test_inactive_rider_and_conflicts_skipped(db):
    inactive = make_person(db, "BD Gone")
    clash = make_person(db, "BD Clash")
    make_ev(db, "EV-BD2", provider="Raft", model="Regular")
    make_ev(db, "EV-BD3", provider="Raft", model="Regular")
    # clash already holds a central EV
    assign(db, clash, "EV-BD3", charged_through="2026-08-31")
    _seed_bd(db)
    db.execute(
        "INSERT INTO bluedart_riders (person_id, bd_rider_id, name, is_active) "
        "VALUES (?, 'BD010', 'BD Gone', 0)",
        (inactive,),
    )
    db.execute(
        "INSERT INTO bluedart_riders (person_id, bd_rider_id, name, is_active) "
        "VALUES (?, 'BD011', 'BD Clash', 1)",
        (clash,),
    )
    db.execute(
        "INSERT INTO bluedart_ev (bd_rider_id, ev_id, handover_date) "
        "VALUES (2, 'EV-BD2', '2026-05-01')"
    )
    db.commit()
    _run(db)

    assert not db.execute("SELECT 1 FROM rider_master WHERE rider_id='BD010'").fetchone(), (
        "inactive Blue Dart riders stay historical"
    )
    # clash rider gets the roster row but keeps their existing single assignment
    assert db.execute("SELECT 1 FROM rider_master WHERE rider_id='BD011'").fetchone()
    open_evs = db.execute(
        "SELECT ev_id FROM ev_assignments WHERE person_id=? AND returned_date IS NULL", (clash,)
    ).fetchall()
    assert [r["ev_id"] for r in open_evs] == ["EV-BD3"], "conflicting holding must be skipped"


def test_fresh_database_noop(db):
    # No bluedart tables at all: migration records itself and does nothing.
    db.execute("DELETE FROM schema_migrations WHERE name='0006_collapse_bluedart'")
    db.commit()
    _run(db)
    assert not db.execute("SELECT 1 FROM companies WHERE company_name='BlueDart'").fetchone()
