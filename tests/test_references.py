"""db/references.py must agree with schema.py, and the creator's hard deletes
must survive a person / EV that has daily-ledger and payment rows (they 500'd
on a foreign key before)."""

from __future__ import annotations

import re

import pytest

from payout.db.references import EV_REFS, PERSON_REFS, purge_ev, purge_person
from payout.db.schema import SCHEMA
from tests.conftest import assign, make_ev, make_person, make_rider


def _refs_in_schema(target: str) -> set[tuple[str, str]]:
    found = set()
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", SCHEMA, re.S):
        table, body = m.group(1), m.group(2)
        for col_m in re.finditer(
            r"^\s*(\w+)\s+\w+[^\n]*?REFERENCES\s+" + target + r"\(", body, re.M
        ):
            found.add((table, col_m.group(1)))
    return found


def test_person_refs_match_schema():
    assert set(PERSON_REFS) == _refs_in_schema("person_registry")


# ev_closeouts / ev_closeout_reports do not declare a foreign key to
# ev_units — they key on ev_assignments(assignment_id) — but they carry the
# ev_id, and they must be cleared before ev_assignments or that assignment's
# DELETE trips their key. So EV_REFS covers more than the declared references.
_EV_INDIRECT = {("ev_closeouts", "ev_id"), ("ev_closeout_reports", "ev_id")}


def test_ev_refs_match_schema():
    assert set(EV_REFS) == _refs_in_schema("ev_units") | _EV_INDIRECT


def test_ev_refs_clear_the_closeouts_before_the_assignments():
    order = [t for t, _ in EV_REFS]
    for table, _ in _EV_INDIRECT:
        assert order.index(table) < order.index("ev_assignments")


def _person_with_history(db):
    pid = make_person(db, "H", balance=-100, arrears=500)
    make_rider(db, pid, "H1", "Kaptan", "H")
    make_ev(db, "EVH", provider="Raft", model="Regular")
    assign(db, pid, "EVH", charged_through="2026-06-07")
    tid = db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after) VALUES (?,?,?,?,?,'PAYOUT',1000,1000)",
        (pid, "H1", "Kaptan", "2026-06-01", "2026-06-07"),
    ).lastrowid
    db.execute(
        "INSERT INTO ev_daily_ledger (ev_id, day, state, assigned_person_id, daily_cost, "
        "provider_cost, billing_status, cycle_event_id) VALUES ('EVH','2026-06-01','billable',?,17857,17857,'billed',?)",  # noqa: E501
        (pid, tid),
    )
    uid = db.execute(
        "INSERT INTO payment_uploads (file_name, uploaded_by) VALUES ('mis.pdf','t')"
    ).lastrowid
    db.execute(
        "INSERT INTO payment_lines (upload_id, line_no, amount, person_id, transaction_id) "
        "VALUES (?,1,1000,?,?)",
        (uid, pid, tid),
    )
    db.execute(
        "INSERT INTO cod_holds (cycle_start, cycle_end, company, rider_id, person_id, worker_code, "
        "amount, source) VALUES ('2026-06-01','2026-06-07','Kaptan','H1',?,'H1',100,'x')",
        (pid,),
    )
    db.execute("INSERT INTO status_tracking (person_id, status) VALUES (?, 'active')", (pid,))
    db.commit()
    return pid


def test_purge_person_with_full_history(db):
    pid = _person_with_history(db)
    purge_person(db, pid)
    db.commit()
    for table, col in PERSON_REFS:
        assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (pid,)).fetchone()[0] == 0
    assert (
        db.execute("SELECT COUNT(*) FROM person_registry WHERE person_id=?", (pid,)).fetchone()[0]
        == 0
    )


def test_purge_ev_with_ledger_rows(db):
    _person_with_history(db)
    purge_ev(db, "EVH")
    db.commit()
    for table, col in EV_REFS:
        assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}='EVH'").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM ev_units WHERE ev_id='EVH'").fetchone()[0] == 0


@pytest.mark.parametrize("route", ["person", "ev"])
def test_creator_delete_routes_do_not_500(db, route):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    pid = _person_with_history(db)
    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("cre@t.test", hash_password("Creator-pass-1"), "creator"),
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        assert (
            c.post(
                "/api/auth/login", data={"username": "cre@t.test", "password": "Creator-pass-1"}
            ).status_code
            == 200
        )
        url = f"/api/creator/persons/{pid}" if route == "person" else "/api/creator/evs/EVH"
        r = c.delete(url)
        assert r.status_code == 200, r.text
        assert r.json()["deleted"] is True


# ── renaming a rider id ──────────────────────────────────────────────────────
def test_rider_refs_cover_every_table_holding_a_rider_id():
    """A rider_id is a text copy, not a foreign key, so nothing in the schema
    enforces this — the list has to be kept by hand. Guard it by finding the
    columns instead: every ``rider_id`` column outside rider_master's own PK
    must be in RIDER_REFS."""
    from payout.db.references import RIDER_REFS

    found = set()
    for m in re.finditer(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\n\);", SCHEMA, re.S):
        table, body = m.group(1), m.group(2)
        for col_m in re.finditer(r"^\s*(\w*rider_id)\s+TEXT", body, re.M):
            found.add((table, col_m.group(1)))
    # companies.rider_id_column names a spreadsheet column, not a rider.
    found -= {("companies", "rider_id_column")}
    assert found == {(t, c) for t, c, _ in RIDER_REFS}


def test_rename_rider_id_moves_history_and_the_feed(db):
    from payout.db.references import rename_rider_id

    pid = make_person(db, "Suman Mondal")
    make_rider(db, pid, "67163_MN0W000471", "Myntra", "Suman Mondal")
    for table, cols, vals in (
        (
            "transactions",
            "person_id, rider_id, company, cycle_start, cycle_end, event_type, amount, "
            "balance_after",
            (pid, "67163_MN0W000471", "Myntra", "2026-09-08", "2026-09-14", "PAYOUT", 100, 100),
        ),
        (
            "cod_holds",
            "cycle_start, cycle_end, company, rider_id, person_id, worker_code, amount, source",
            ("2026-09-08", "2026-09-14", "Myntra", "67163_MN0W000471", pid, "w", 50, "x"),
        ),
        (
            "salary_inputs",
            "company, cycle_start, cycle_end, rider_id, person_id",
            ("Myntra", "2026-09-08", "2026-09-14", "67163_MN0W000471", pid),
        ),
    ):
        db.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(vals))})",  # noqa: S608
            vals,
        )
    db.execute(
        "UPDATE person_registry SET deduction_company='Myntra', "
        "deduction_rider_id='67163_MN0W000471' WHERE person_id=?",
        (pid,),
    )
    db.execute(
        "INSERT INTO activity_log (email, action, entity_type, entity_id, person_id) "
        "VALUES ('r@t.test', 'rider.create', 'rider', '67163_MN0W000471@Myntra', ?)",
        (pid,),
    )
    db.commit()

    assert rename_rider_id(db, "Myntra", "67163_MN0W000471", "67163_MNOW000471")
    db.commit()

    for table in ("rider_master", "transactions", "cod_holds", "salary_inputs"):
        left = db.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE rider_id='67163_MN0W000471'"  # noqa: S608
        ).fetchone()["n"]
        moved = db.execute(
            f"SELECT COUNT(*) AS n FROM {table} WHERE rider_id='67163_MNOW000471'"  # noqa: S608
        ).fetchone()["n"]
        assert (left, moved) == (0, 1), table
    assert (
        db.execute(
            "SELECT deduction_rider_id FROM person_registry WHERE person_id=?", (pid,)
        ).fetchone()["deduction_rider_id"]
        == "67163_MNOW000471"
    )
    assert (
        db.execute("SELECT entity_id FROM activity_log").fetchone()["entity_id"]
        == "67163_MNOW000471@Myntra"
    )


def test_rename_rider_id_refuses_a_taken_id_and_a_no_op(db):
    from payout.db.references import rename_rider_id

    a = make_person(db, "A")
    b = make_person(db, "B")
    make_rider(db, a, "R-1", "Myntra", "A")
    make_rider(db, b, "R-2", "Myntra", "B")
    db.commit()
    assert not rename_rider_id(db, "Myntra", "R-1", "R-2")  # taken: merge, don't rename
    assert not rename_rider_id(db, "Myntra", "R-1", "R-1")  # same value
    assert not rename_rider_id(db, "Spencer's", "R-1", "R-9")  # not at that company
    assert db.execute("SELECT COUNT(*) AS n FROM rider_master").fetchone()["n"] == 2


def test_rename_rider_id_leaves_the_same_id_at_another_company_alone(db):
    """rider_master is keyed (rider_id, company): the same id at two companies
    is two different riders."""
    from payout.db.references import rename_rider_id

    a = make_person(db, "A")
    b = make_person(db, "B")
    make_rider(db, a, "SHARED-1", "Myntra", "A")
    make_rider(db, b, "SHARED-1", "Jiffy", "B")
    db.commit()
    assert rename_rider_id(db, "Myntra", "SHARED-1", "SHARED-2")
    db.commit()
    assert (
        db.execute("SELECT company FROM rider_master WHERE rider_id='SHARED-1'").fetchone()[
            "company"
        ]
        == "Jiffy"
    )
