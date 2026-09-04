from datetime import date

from payout.domain.rent import advance_rent_charged_through, resolve_rent


def _blive(db):
    pid = db.execute("INSERT INTO person_registry (display_name) VALUES ('C')").lastrowid
    db.execute("INSERT OR IGNORE INTO balances (person_id,current_balance) VALUES (?,0)", (pid,))
    mid = db.execute("SELECT model_id FROM ev_models WHERE provider='Blive'").fetchone()["model_id"]
    ev = f"B{pid}"
    db.execute("INSERT INTO ev_units (ev_id,model_id,status) VALUES (?,?, 'in_use')", (ev, mid))
    db.execute("INSERT INTO ev_assignments (person_id,ev_id) VALUES (?, ?)", (pid, ev))
    db.commit()
    return pid


def test_contiguous_weeks(db):
    pid = _blive(db)
    r1 = resolve_rent(db, pid, date(2026, 3, 2), date(2026, 3, 8))
    assert r1.days == 7 and r1.rent == 126000.0
    advance_rent_charged_through(db, pid, date(2026, 3, 8))
    db.commit()
    r2 = resolve_rent(db, pid, date(2026, 3, 9), date(2026, 3, 15))
    assert r2.rent_from == date(2026, 3, 9) and r2.days == 7 and r2.rent == 126000.0


def test_unaccounted_gap_behind_meter_is_caught_up(db):
    """The meter sits at Mar 8 and no cycle ever covered Mar 9-15: those days
    are owed and nothing else will ever bill them, so the next cycle that
    processes the rider reaches back over them (2026-09-04, Jeet Ghosh)."""
    pid = _blive(db)
    advance_rent_charged_through(db, pid, date(2026, 3, 8))
    db.commit()
    r = resolve_rent(db, pid, date(2026, 3, 16), date(2026, 3, 22))
    assert r.rent_from == date(2026, 3, 9) and r.days == 14 and r.rent == 252000.0
    assert r.catchup_days == 7 and r.orphan_gap_days == 0


def test_gap_already_in_arrears_is_not_caught_up(db):
    """The same behind meter, but Mar 9-15 was already missed to arrears (a
    RENT_MISSED window covers it): reaching back would double-charge, so the
    cycle bills only its own 7 days."""
    pid = _blive(db)
    advance_rent_charged_through(db, pid, date(2026, 3, 8))
    db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, days) "
        "VALUES (?, 'B1', 'Blitz', '2026-03-09', '2026-03-15', 'RENT_MISSED', -126000, 0, 7)",
        (pid,),
    )
    db.commit()
    r = resolve_rent(db, pid, date(2026, 3, 16), date(2026, 3, 22))
    assert r.rent_from == date(2026, 3, 16) and r.days == 7 and r.rent == 126000.0
    assert r.catchup_days == 0


def test_overlap_not_double_charged(db):
    pid = _blive(db)
    advance_rent_charged_through(db, pid, date(2026, 3, 8))
    db.commit()
    r = resolve_rent(db, pid, date(2026, 3, 2), date(2026, 3, 8))  # re-run same cycle
    assert r.days == 0 and r.rent == 0.0
