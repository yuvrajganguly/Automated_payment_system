"""Run with the configured database, first --dry-run, then --apply --backup PATH.

Stop payout processing during maintenance. Store pg_dump outside the repository.
This does not repair payout cycles or adjust any rider's money.
"""

import argparse
import json
from pathlib import Path

from payout.company_consolidation import consolidate_blitz
from payout.db import get_connection


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
        parser.error("--apply requires a nonempty database backup file")
    conn = get_connection()
    try:
        # The outer transaction also makes RELEASE SAVEPOINT noncommitting on SQLite.
        conn.execute("BEGIN")
        report = consolidate_blitz(conn)
        if args.apply:
            conn.commit()
        else:
            conn.rollback()
        print(json.dumps({"applied": args.apply, **report}))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
