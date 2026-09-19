"""The duplicate-person / phantom-EV cleanup (2026-09-17).

A recruiter re-onboarded riders the office had already added, and typed the EV
id with a confusable character — J for I, O for zero — so the second rider was
handed a second vehicle that does not exist. This is the cleanup, run from
``payout.cli.dedupe``, and the cases below are the live data's shape.

The rules worth defending:
  * a phantom is only deleted when the unit it is a typo of really exists;
  * the copy holding the real vehicle is the one that survives;
  * a shared name alone never merges two people — two men are called Bidhan
    Mondal — but a shared name plus a shared phone or account does;
  * rent is NOT reversed: the phantom's day rows go, the money stays.
"""

from __future__ import annotations

from payout.cli import dedupe
from tests.conftest import assign, make_ev, make_person, make_rider

# The matcher itself is tested in test_duplicates.py — it lives in
# domain/duplicates.py so this tool and the entry-time checks share one copy.


# ── the fixture: the live shape ──────────────────────────────────────────────
def _live(db):
    """Two men each holding a real EV and a phantom, plus three name pairs."""
    ids = {}
    # Shibam Pramanick: office copy holds the real unit, recruiter copy the typo.
    ids["shibam_real"] = make_person(db, "Shibam Pramanick")
    ids["shibam_dupe"] = make_person(db, "Shibam Pramanick", balance=-70000, arrears=45000)
    make_rider(db, ids["shibam_real"], "QSPEND0031", "Jiffy", "Shibam Pramanick")
    make_rider(db, ids["shibam_dupe"], "7003664227", "Jiffy", "Shibam Pramanick")
    db.execute("UPDATE rider_master SET mob_no='7003664227' WHERE company='Jiffy'")
    make_ev(db, "CBICEVD0250", status="in_use")
    make_ev(db, "CBJCEVD0250", status="in_use")
    assign(db, ids["shibam_real"], "CBICEVD0250", handover="2026-09-08")
    assign(db, ids["shibam_dupe"], "CBJCEVD0250", handover="2026-09-12")
    for day in ("2026-09-12", "2026-09-13", "2026-09-14"):
        db.execute(
            "INSERT INTO ev_daily_ledger (ev_id, day, state, assigned_person_id, daily_cost, "
            "provider_cost, billing_status) VALUES (?, ?, 'billable', ?, 10000, 10000, 'billed')",
            ("CBJCEVD0250", day, ids["shibam_dupe"]),
        )

    # Suman Mondal: the phantom copy carries the real Myntra id.
    ids["suman_real"] = make_person(db, "Suman Mondal")
    ids["suman_dupe"] = make_person(db, "Suman Mondal")
    make_rider(db, ids["suman_real"], "QSPEND0034", "Jiffy", "Suman Mondal")
    make_rider(db, ids["suman_dupe"], "67163_MNOW000471", "Myntra", "Suman Mondal")
    db.execute(
        "UPDATE rider_master SET account_no='9988776655' WHERE rider_id IN "
        "('QSPEND0034', '67163_MNOW000471')"
    )
    make_ev(db, "CBICEVD0286", status="in_use")
    make_ev(db, "CBICEVDO286", status="in_use")
    assign(db, ids["suman_real"], "CBICEVD0286", handover="2026-09-10")
    assign(db, ids["suman_dupe"], "CBICEVDO286", handover="2026-09-12")

    # Same name, same phone, no EV — merges.
    ids["bidhan_a"] = make_person(db, "BIDHAN MONDAL")
    ids["bidhan_b"] = make_person(db, "Bidhan Mondal")
    make_rider(db, ids["bidhan_a"], "R-100", "Jiffy", "BIDHAN MONDAL")
    make_rider(db, ids["bidhan_b"], "R-101", "Jiffy", "Bidhan Mondal")
    db.execute("UPDATE rider_master SET mob_no='9000000001' WHERE rider_id IN ('R-100','R-101')")

    # Same name, DIFFERENT phone — two different men, must not merge.
    ids["rahul_a"] = make_person(db, "Rahul Das")
    ids["rahul_b"] = make_person(db, "Rahul Das")
    make_rider(db, ids["rahul_a"], "R-200", "Jiffy", "Rahul Das")
    make_rider(db, ids["rahul_b"], "R-201", "Jiffy", "Rahul Das")
    db.execute("UPDATE rider_master SET mob_no='9000000002' WHERE rider_id='R-200'")
    db.execute("UPDATE rider_master SET mob_no='9000000003' WHERE rider_id='R-201'")

    # Same phone, unrelated names — reported, never merged.
    ids["akash"] = make_person(db, "Akash Roy")
    ids["biplab"] = make_person(db, "Biplab Halder")
    make_rider(db, ids["akash"], "R-300", "Jiffy", "Akash Roy")
    make_rider(db, ids["biplab"], "R-301", "Jiffy", "Biplab Halder")
    db.execute("UPDATE rider_master SET mob_no='9000000004' WHERE rider_id IN ('R-300','R-301')")
    db.commit()
    return ids


def _patch_known(monkeypatch, ids):
    """Point the hand-confirmed list at the fixture's ids."""
    monkeypatch.setattr(
        dedupe,
        "KNOWN_PAIRS",
        (
            (ids["shibam_real"], ids["shibam_dupe"]),
            (ids["suman_real"], ids["suman_dupe"]),
        ),
    )


def _run(db, monkeypatch, ids, *argv):
    """Run main() against the test connection (it opens its own otherwise)."""

    class _Keep:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(dedupe, "get_connection", lambda: _Keep())
    _patch_known(monkeypatch, ids)
    return dedupe.main(list(argv))


# ── the dry run changes nothing ──────────────────────────────────────────────
def test_dry_run_touches_nothing(db, monkeypatch, capsys):
    ids = _live(db)
    assert _run(db, monkeypatch, ids) == 0
    out = capsys.readouterr().out
    assert "dry run" in out
    assert db.execute("SELECT COUNT(*) AS n FROM ev_units").fetchone()["n"] == 4
    assert db.execute("SELECT COUNT(*) AS n FROM person_registry").fetchone()["n"] == 10


def test_dry_run_names_the_rent_it_will_not_reverse(db, monkeypatch, capsys):
    ids = _live(db)
    _run(db, monkeypatch, ids)
    out = capsys.readouterr().out
    assert "300" in out  # 3 days x 10000 paise
    assert "NOT reversed" in out


# ── applying it ──────────────────────────────────────────────────────────────
def test_apply_deletes_the_phantoms_and_keeps_the_real_units(db, monkeypatch):
    ids = _live(db)
    _run(db, monkeypatch, ids, "--apply")
    left = {r["ev_id"] for r in db.execute("SELECT ev_id FROM ev_units").fetchall()}
    assert left == {"CBICEVD0250", "CBICEVD0286"}
    assert db.execute("SELECT COUNT(*) AS n FROM ev_daily_ledger").fetchone()["n"] == 0
    assert db.execute("SELECT COUNT(*) AS n FROM ev_assignments").fetchone()["n"] == 2


def test_the_copy_holding_the_real_vehicle_survives(db, monkeypatch):
    ids = _live(db)
    _run(db, monkeypatch, ids, "--apply")
    for real, dupe in (("shibam_real", "shibam_dupe"), ("suman_real", "suman_dupe")):
        assert db.execute(
            "SELECT 1 FROM person_registry WHERE person_id=?", (ids[real],)
        ).fetchone()
        assert not db.execute(
            "SELECT 1 FROM person_registry WHERE person_id=?", (ids[dupe],)
        ).fetchone()


def test_the_duplicate_rider_ids_follow_the_survivor(db, monkeypatch):
    ids = _live(db)
    _run(db, monkeypatch, ids, "--apply")
    rows = {
        r["rider_id"]: r["company"]
        for r in db.execute(
            "SELECT rider_id, company FROM rider_master WHERE person_id=?", (ids["suman_real"],)
        ).fetchall()
    }
    # The real Myntra id came across. The Jiffy placeholder stays: placeholders
    # retire per company, and we still have no real Jiffy id for this man.
    assert rows == {"QSPEND0034": "Jiffy", "67163_MNOW000471": "Myntra"}


def test_rent_is_not_reversed_it_follows_the_person(db, monkeypatch):
    ids = _live(db)
    _run(db, monkeypatch, ids, "--apply")
    bal = db.execute(
        "SELECT current_balance FROM balances WHERE person_id=?", (ids["shibam_real"],)
    ).fetchone()
    arr = db.execute(
        "SELECT outstanding FROM ev_arrears WHERE person_id=?", (ids["shibam_real"],)
    ).fetchone()
    assert int(bal["current_balance"]) == -70000
    assert int(arr["outstanding"]) == 45000


def test_same_name_without_a_shared_identifier_is_left_alone(db, monkeypatch, capsys):
    ids = _live(db)
    _run(db, monkeypatch, ids, "--apply")
    capsys.readouterr()
    for key in ("rahul_a", "rahul_b"):
        assert db.execute(
            "SELECT 1 FROM person_registry WHERE person_id=?", (ids[key],)
        ).fetchone(), "two different men called Rahul Das were merged"


def test_same_name_and_shared_phone_merges_without_being_listed(db, monkeypatch):
    ids = _live(db)
    _run(db, monkeypatch, ids, "--apply")
    alive = [
        k
        for k in ("bidhan_a", "bidhan_b")
        if db.execute("SELECT 1 FROM person_registry WHERE person_id=?", (ids[k],)).fetchone()
    ]
    assert alive == ["bidhan_a"]  # the older record keeps the name


def test_a_shared_phone_with_unrelated_names_is_reported_not_merged(db, monkeypatch, capsys):
    ids = _live(db)
    _run(db, monkeypatch, ids, "--apply")
    out = capsys.readouterr().out
    assert "Akash Roy" in out and "Biplab Halder" in out
    assert "decide these yourself" in out
    for key in ("akash", "biplab"):
        assert db.execute("SELECT 1 FROM person_registry WHERE person_id=?", (ids[key],)).fetchone()


def test_also_merge_forces_a_reported_pair(db, monkeypatch):
    ids = _live(db)
    _run(db, monkeypatch, ids, "--apply", "--also-merge", f"{ids['akash']}:{ids['biplab']}")
    alive = [
        k
        for k in ("akash", "biplab")
        if db.execute("SELECT 1 FROM person_registry WHERE person_id=?", (ids[k],)).fetchone()
    ]
    assert len(alive) == 1


# ── refusals ─────────────────────────────────────────────────────────────────
def test_a_phantom_whose_real_twin_is_missing_is_not_deleted(db, monkeypatch, capsys):
    ids = _live(db)
    db.execute("DELETE FROM ev_daily_ledger WHERE ev_id='CBICEVD0250'")
    db.execute("UPDATE ev_assignments SET ev_id='CBJCEVD0250' WHERE ev_id='CBICEVD0250'")
    db.execute("DELETE FROM ev_units WHERE ev_id='CBICEVD0250'")
    db.commit()
    _run(db, monkeypatch, ids, "--apply")
    out = capsys.readouterr().out
    assert "SKIPPED" in out
    assert db.execute("SELECT 1 FROM ev_units WHERE ev_id='CBJCEVD0250'").fetchone()


def test_two_people_each_holding_a_real_ev_are_never_merged(db, monkeypatch, capsys):
    ids = _live(db)
    # Give the Bidhans one real EV each: now they might be two men, so stop.
    make_ev(db, "REAL-A", status="in_use")
    make_ev(db, "REAL-B", status="in_use")
    assign(db, ids["bidhan_a"], "REAL-A", handover="2026-09-01")
    assign(db, ids["bidhan_b"], "REAL-B", handover="2026-09-01")
    db.commit()
    _run(db, monkeypatch, ids, "--apply")
    out = capsys.readouterr().out
    assert "both hold an EV" in out
    for key in ("bidhan_a", "bidhan_b"):
        assert db.execute("SELECT 1 FROM person_registry WHERE person_id=?", (ids[key],)).fetchone()


def test_a_closeout_on_the_phantom_does_not_break_the_delete(db, monkeypatch):
    """ev_closeouts keys on assignment_id, which db.references.EV_REFS does not
    cover — deleting the assignment first would trip its foreign key."""
    ids = _live(db)
    aid = db.execute(
        "SELECT assignment_id FROM ev_assignments WHERE ev_id='CBJCEVD0250'"
    ).fetchone()["assignment_id"]
    db.execute(
        "INSERT INTO ev_closeout_reports (assignment_id, ev_id, person_id, reported_by) "
        "VALUES (?, 'CBJCEVD0250', ?, 'r@t.test')",
        (aid, ids["shibam_dupe"]),
    )
    db.commit()
    _run(db, monkeypatch, ids, "--apply")
    assert not db.execute("SELECT 1 FROM ev_units WHERE ev_id='CBJCEVD0250'").fetchone()
    assert db.execute("SELECT COUNT(*) AS n FROM ev_closeout_reports").fetchone()["n"] == 0


def test_running_it_twice_is_a_no_op(db, monkeypatch, capsys):
    ids = _live(db)
    _run(db, monkeypatch, ids, "--apply")
    before = db.execute("SELECT COUNT(*) AS n FROM person_registry").fetchone()["n"]
    capsys.readouterr()
    _run(db, monkeypatch, ids, "--apply")
    out = capsys.readouterr().out
    assert "already gone" in out
    assert db.execute("SELECT COUNT(*) AS n FROM person_registry").fetchone()["n"] == before


# ── the foreign key purge_ev used to miss ────────────────────────────────────
def test_creator_delete_ev_survives_a_closeout_report(db):
    """db.references.EV_REFS left the two close-out tables out, so deleting an
    EV that had ever been closed out raised a foreign-key error the creator's
    delete returned as a bare 500."""
    from payout.db.references import purge_ev

    pid = make_person(db, "Closed Out")
    make_ev(db, "GONE-1", status="in_use")
    aid = assign(db, pid, "GONE-1", handover="2026-08-01", returned="2026-08-20")
    db.execute(
        "INSERT INTO ev_closeout_reports (assignment_id, ev_id, person_id, reported_by) "
        "VALUES (?, 'GONE-1', ?, 'r@t.test')",
        (aid, pid),
    )
    db.execute(
        "INSERT INTO ev_closeouts (assignment_id, ev_id, person_id) VALUES (?, 'GONE-1', ?)",
        (aid, pid),
    )
    db.commit()
    purge_ev(db, "GONE-1")
    db.commit()
    assert not db.execute("SELECT 1 FROM ev_units WHERE ev_id='GONE-1'").fetchone()
    assert db.execute("SELECT COUNT(*) AS n FROM ev_closeouts").fetchone()["n"] == 0
