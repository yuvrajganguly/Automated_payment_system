from payout.domain.reconciliation import provider_rider_reconciliation


def _seed(conn):
    mid = conn.execute(
        "SELECT model_id FROM ev_models WHERE provider='Raft' AND model_name='Regular'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO ev_units (ev_id, model_id, status) VALUES ('EV1',?, 'in_use')", (mid,)
    )
    pid = conn.execute("INSERT INTO person_registry (display_name) VALUES ('Asha')").lastrowid
    conn.execute("INSERT OR IGNORE INTO balances (person_id,current_balance) VALUES (?,0)", (pid,))
    # a RENT transaction (the collecting company) the billed days point to
    tid = conn.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after) VALUES (?,?,?,?,?,'RENT',?,0)",
        (pid, "J1", "Jiffy", "2026-03-02", "2026-03-08", -540),
    ).lastrowid
    daily = 1260 / 7.0
    # 3 days billed (collected via Jiffy), 2 days missed
    for d, status, ev in [
        ("2026-03-02", "billed", tid),
        ("2026-03-03", "billed", tid),
        ("2026-03-04", "billed", tid),
        ("2026-03-05", "missed", None),
        ("2026-03-06", "missed", None),
    ]:
        conn.execute(
            "INSERT INTO ev_daily_ledger (ev_id, day, state, assigned_person_id, "
            "daily_cost, provider_cost, billing_status, cycle_event_id) "
            "VALUES ('EV1',?,'billable',?,?,?,?,?)",
            (d, pid, daily, daily, status, ev),
        )
    conn.commit()
    return pid


def test_reconciliation_basic(db):
    pid = _seed(db)  # noqa: F841
    out = provider_rider_reconciliation(db, "Raft", "2026-03-02", "2026-03-08")
    assert out["totals"]["rider_count"] == 1
    row = out["rows"][0]
    daily = 1260 / 7.0
    assert row["expected"] == round(5 * daily, 2)
    assert row["collected"] == round(3 * daily, 2)
    assert row["missed"] == round(2 * daily, 2)
    assert row["settled_via"] == "Jiffy"  # collected elsewhere, surfaced
    assert row["collection_pct"] == round(100 * 3 / 5, 1)


def test_reconciliation_provider_scoped(db):
    _seed(db)
    # Blive has no EVs/ledger here -> empty
    out = provider_rider_reconciliation(db, "Blive", "2026-03-02", "2026-03-08")
    assert out["rows"] == []
    assert out["totals"]["expected"] == 0
