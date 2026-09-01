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
        for col_m in re.finditer(r"^\s*(\w+)\s+\w+[^\n]*?REFERENCES\s+" + target + r"\(", body, re.M):
            found.add((table, col_m.group(1)))
    return found


def test_person_refs_match_schema():
    assert set(PERSON_REFS) == _refs_in_schema("person_registry")


def test_ev_refs_match_schema():
    assert set(EV_REFS) == _refs_in_schema("ev_units")


def _person_with_history(db):
    pid = make_person(db, "H", balance=-100, arrears=500)
    make_rider(db, pid, "H1", "Blitz", "H")
    make_ev(db, "EVH", provider="Raft", model="Regular")
    assign(db, pid, "EVH", charged_through="2026-06-07")
    tid = db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after) VALUES (?,?,?,?,?,'PAYOUT',1000,1000)",
        (pid, "H1", "Blitz", "2026-06-01", "2026-06-07"),
    ).lastrowid
    db.execute(
        "INSERT INTO ev_daily_ledger (ev_id, day, state, assigned_person_id, daily_cost, "
        "provider_cost, billing_status, cycle_event_id) VALUES ('EVH','2026-06-01','billable',?,17857,17857,'billed',?)",
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
        "amount, source) VALUES ('2026-06-01','2026-06-07','Blitz','H1',?,'H1',100,'x')",
        (pid,),
    )
    db.execute(
        "INSERT INTO status_tracking (person_id, status) VALUES (?, 'active')", (pid,)
    )
    db.commit()
    return pid


def test_purge_person_with_full_history(db):
    pid = _person_with_history(db)
    purge_person(db, pid)
    db.commit()
    for table, col in PERSON_REFS:
        assert db.execute(f"SELECT COUNT(*) FROM {table} WHERE {col}=?", (pid,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM person_registry WHERE person_id=?", (pid,)).fetchone()[0] == 0


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
        assert c.post("/api/auth/login",
                      data={"username": "cre@t.test", "password": "Creator-pass-1"}).status_code == 200
        url = f"/api/creator/persons/{pid}" if route == "person" else "/api/creator/evs/EVH"
        r = c.delete(url)
        assert r.status_code == 200, r.text
        assert r.json()["deleted"] is True
