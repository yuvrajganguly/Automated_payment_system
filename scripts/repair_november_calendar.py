"""November 2026 incident: metadata only; --dry-run before --apply --backup PATH.

Pending schema migrations run inside the same transaction as the repair.
"""

import argparse
import hashlib
import json
from pathlib import Path

from payout.company_consolidation import consolidate_blitz
from payout.config import DB_URL
from payout.cycle_calendar import correct_cycle
from payout.db import get_connection
from payout.db.migrations import run_migrations


def money_fingerprint(conn):
    snapshots = []
    for query in (
        "SELECT person_id,current_balance,pending_xc_rent FROM balances ORDER BY person_id",
        "SELECT * FROM ev_arrears ORDER BY person_id",
        "SELECT * FROM ev_assignments ORDER BY assignment_id",
        "SELECT id,person_id,event_type,amount,balance_after,cycle_start,cycle_end "
        "FROM transactions ORDER BY id",
    ):
        snapshots.append([tuple(row) for row in conn.execute(query)])
    return hashlib.sha256(json.dumps(snapshots, default=str).encode()).hexdigest()


def repair(conn):
    before = money_fingerprint(conn)
    changes = 0
    for company, window, retained in (
        ("Jiffy", ("2026-11-08", "2026-11-08"), ("2026-11-01", "2026-11-07")),
        ("Myntra", ("2026-10-12", "2026-10-13"), ("2026-10-05", "2026-10-11")),
        ("Myntra", ("2026-10-21", "2026-10-21"), ("2026-10-14", "2026-10-20")),
    ):
        changes += correct_cycle(conn, company, *window, duplicate_of=retained)
    blitz = (
        "Kaptan"
        if conn.execute("SELECT 1 FROM companies WHERE company_name='Kaptan'").fetchone()
        else "Blitz"
    )
    for company, windows in (
        (
            blitz,
            (
                ("2026-10-11", "2026-10-17", "2026-10-04", "2026-10-10"),
                ("2026-10-18", "2026-10-20", "2026-10-11", "2026-10-17"),
                ("2026-10-21", "2026-10-27", "2026-10-18", "2026-10-24"),
                ("2026-10-28", "2026-11-03", "2026-10-25", "2026-10-31"),
                ("2026-11-04", "2026-11-10", "2026-11-01", "2026-11-07"),
            ),
        ),
        (
            "Myntra",
            (
                ("2026-10-14", "2026-10-20", "2026-10-12", "2026-10-18"),
                ("2026-10-22", "2026-10-28", "2026-10-19", "2026-10-25"),
                ("2026-11-01", "2026-11-07", "2026-10-26", "2026-11-01"),
                ("2026-11-08", "2026-11-14", "2026-11-02", "2026-11-08"),
            ),
        ),
    ):
        for old_start, old_end, new_start, new_end in windows:
            changes += correct_cycle(conn, company, old_start, old_end, (new_start, new_end))
    merge = consolidate_blitz(conn)
    # Runs entered while the original repair was pending; the operator
    # confirmed that both belong to the next 8–14 November week.
    for company in ("Jiffy", "Blitz"):
        changes += correct_cycle(
            conn, company, "2026-11-11", "2026-11-17", ("2026-11-08", "2026-11-14")
        )
    if money_fingerprint(conn) != before:
        raise RuntimeError("Financial state changed; refusing to commit")
    return {"calendar_changes": changes, "merge": merge, "money_unchanged": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.apply and (
        not args.backup or not args.backup.is_file() or not args.backup.stat().st_size
    ):
        parser.error("--apply requires a nonempty pg_dump backup file")
    conn = get_connection()
    try:
        conn.execute("BEGIN")
        if DB_URL:
            # PostgreSQL-only maintenance lock; normal app SQL remains portable.
            conn.execute(
                "LOCK TABLE transactions, balances, ev_arrears, ev_assignments, "
                "rider_master, companies, company_cycles IN SHARE ROW EXCLUSIVE MODE"
            )
        run_migrations(conn, fresh_database=False)
        report = repair(conn)
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
        print(json.dumps({"applied": args.apply, **report}))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
