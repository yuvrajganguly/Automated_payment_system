from payout.domain.ev_daily import attribute_pending


def _seed_pending(db, ev, days, daily=180.0):
    mid = db.execute("SELECT model_id FROM ev_models WHERE provider='Raft' LIMIT 1").fetchone()[0]
    db.execute("INSERT INTO ev_units (ev_id, model_id, status) VALUES (?,?, 'in_use')", (ev, mid))
    pid = db.execute("INSERT INTO person_registry (display_name) VALUES ('M')").lastrowid
    for d in days:
        db.execute(
            "INSERT INTO ev_daily_ledger (ev_id, day, state, assigned_person_id, "
            "daily_cost, provider_cost, billing_status) VALUES (?,?, 'billable',?,?,?,NULL)",
            (ev, d, pid, daily, daily),
        )
    db.commit()
    return pid


def test_attribute_pending_flips_to_billed_up_to_amount(db):
    pid = _seed_pending(db, "EVZ", ["2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04"])
    applied = attribute_pending(
        db,
        person_id=pid,
        event_id=999,
        amount=2 * 180.0,
        day_from="2026-05-01",
        day_to="2026-05-31",
    )
    db.commit()
    assert applied == round(2 * 180.0, 2)
    billed = db.execute(
        "SELECT COUNT(*) FROM ev_daily_ledger WHERE assigned_person_id=? AND billing_status='billed'",  # noqa: E501
        (pid,),
    ).fetchone()[0]
    pending = db.execute(
        "SELECT COUNT(*) FROM ev_daily_ledger WHERE assigned_person_id=? "
        "AND billing_status IS NULL AND state='billable'",
        (pid,),
    ).fetchone()[0]
    assert billed == 2 and pending == 2


def test_attribute_pending_respects_window(db):
    pid = _seed_pending(db, "EVW", ["2026-05-10", "2026-06-10"])
    applied = attribute_pending(
        db, person_id=pid, event_id=1, amount=10 * 180.0, day_from="2026-05-01", day_to="2026-05-31"
    )
    db.commit()
    assert applied == round(180.0, 2)  # only the in-window May day
    juned = db.execute(
        "SELECT billing_status FROM ev_daily_ledger WHERE day='2026-06-10'"
    ).fetchone()[0]
    assert juned is None  # June day untouched
