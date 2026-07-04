"""EV lifecycle: assign -> mark-spare -> return-spare, and return works for a
spare directly. Guards the new /evs/to-spare and the spare-aware /evs/return."""
from payout.api.routes.evs import assign_ev, return_ev, mark_spare
from payout.api.schemas import EvAssignIn, EvReturnIn
from payout.db import get_connection

_USER = {"email": "tester@example.com", "role": "admin"}


def _status(ev_id):
    with get_connection() as c:
        return c.execute("SELECT status FROM ev_units WHERE ev_id=?", (ev_id,)).fetchone()["status"]


def _open_assignment(ev_id):
    with get_connection() as c:
        return c.execute(
            "SELECT 1 FROM ev_assignments WHERE ev_id=? AND returned_date IS NULL",
            (ev_id,)).fetchone() is not None


def _setup(db, ev_id="EVZ"):
    pid = db.execute("INSERT INTO person_registry (display_name) VALUES ('R')").lastrowid
    db.execute("INSERT INTO rider_master (rider_id,company,person_id,name,is_active) "
               "VALUES ('R1','Blitz',?,'R',1)", (pid,))
    mid = db.execute("SELECT model_id FROM ev_models WHERE provider='Raft' "
                     "AND model_name='Regular'").fetchone()["model_id"]
    db.execute("INSERT INTO ev_units (ev_id,model_id,status) VALUES (?,?, 'spare')",
               (ev_id, mid))
    db.commit()
    return pid


def test_mark_spare_then_return_spare(db):
    _setup(db, "EVZ")
    assign_ev(EvAssignIn(ev_id="EVZ", rider_id="R1", company="Blitz"), _USER)
    assert _status("EVZ") == "in_use"

    # take it back into the spare pool (rent stops, EV stays available)
    r = mark_spare(EvReturnIn(ev_id="EVZ"), _USER)
    assert r["spare"] is True
    assert _status("EVZ") == "spare"
    assert not _open_assignment("EVZ")          # assignment closed

    # now return the spare to the provider
    r2 = return_ev(EvReturnIn(ev_id="EVZ"), _USER)
    assert r2["returned"] is True
    assert _status("EVZ") == "returned"


def test_return_works_directly_on_a_spare(db):
    _setup(db, "EVS")                            # created as a spare, never assigned
    r = return_ev(EvReturnIn(ev_id="EVS"), _USER)
    assert r["returned"] is True
    assert _status("EVS") == "returned"
