"""Reporting-only repairs. Never settle money or move rent meters."""

from datetime import date

from payout.domain.activity import record_activity


def correct_cycle(conn, company, original_start, original_end, corrected=None, duplicate_of=None):
    """Correct the reporting calendar, or exclude a verified duplicate run.

    The caller owns the transaction. A duplicate must have the same per-person
    gross payout as the retained run (a subset is allowed for partial retries).
    Ledger rows, live balances, arrears and assignments are never modified.
    """
    if conn.execute(
        "SELECT 1 FROM cycle_reporting_adjustments WHERE company=? "
        "AND original_start=? AND original_end=?",
        (company, original_start, original_end),
    ).fetchone():
        return False
    cycle = conn.execute(
        "SELECT * FROM company_cycles WHERE company=? AND cycle_start=? AND cycle_end=?",
        (company, original_start, original_end),
    ).fetchone()
    if not cycle:
        raise ValueError("Expected original cycle does not exist")
    if corrected:
        start, end = map(date.fromisoformat, corrected)
        if start > end:
            raise ValueError("Cycle starts after it ends")
    else:
        if not duplicate_of:
            raise ValueError("Excluding a cycle requires a verified retained run")

        def payouts(window):
            return {
                r[0]: r[1]
                for r in conn.execute(
                    "SELECT person_id,SUM(amount) FROM transactions WHERE company=? "
                    "AND cycle_start=? AND cycle_end=? AND event_type='PAYOUT' GROUP BY person_id",
                    (company, *window),
                )
            }

        duplicate = payouts((original_start, original_end))
        retained = payouts(duplicate_of)
        if not duplicate or any(retained.get(pid) != amount for pid, amount in duplicate.items()):
            raise ValueError("Payouts do not match the retained run")
    reason = "Calendar repair; balances and arrears left for manual reconciliation"
    conn.execute(
        "INSERT INTO cycle_reporting_adjustments "
        "(company,original_start,original_end,corrected_start,corrected_end,excluded,reason,"
        "through_transaction_id,recorded_through) VALUES (?,?,?,?,?,?,?,?,datetime('now'))",
        (
            company,
            original_start,
            original_end,
            *(corrected or (None, None)),
            0 if corrected else 1,
            reason,
            conn.execute("SELECT COALESCE(MAX(id),0) FROM transactions").fetchone()[0],
        ),
    )
    record_activity(
        conn,
        {"email": "maintenance", "role": "creator"},
        "cycle.calendar_repair",
        entity_type="company",
        entity_id=company,
        details={
            "original_cycle": dict(cycle),
            "corrected": corrected,
            "duplicate_of": duplicate_of,
            "money_unchanged": True,
        },
    )
    if corrected:
        year, week, _ = end.isocalendar()
        conn.execute(
            "UPDATE company_cycles SET cycle_start=?,cycle_end=?,week_bucket=? WHERE id=?",
            (*corrected, f"{year}-W{week:02d}", cycle["id"]),
        )
    else:
        # Any workbook was already backed up along with the database.
        conn.execute("DELETE FROM company_cycles WHERE id=?", (cycle["id"],))
    return True
