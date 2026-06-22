"""One-shot migration: convert money columns from rupee floats to integer paise.

Run ONCE against a database created before the paise migration. It:
  1. backs up the DB to <db>.pre_paise_backup,
  2. multiplies every money column by 100 (rounded to the nearest paisa),
  3. records a guard row so re-running is a safe no-op.

Usage:
    python scripts/migrate_to_paise.py [path/to/payout.db]
    # or rely on PAYOUT_DB

Always run it on a COPY first and eyeball a few numbers before pointing
production at the migrated file.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from datetime import datetime

# table -> money columns (rupees -> paise)
MONEY = {
    "ev_models": ["weekly_rate"],
    "ev_arrears": ["total_missed", "total_recovered", "outstanding",
                   "cod_missed", "cod_recovered", "cod_outstanding"],
    "transactions": ["amount", "balance_after"],
    "balances": ["current_balance", "pending_xc_rent"],
    "cod_holds": ["amount"],
    "company_cycles": ["total_release", "total_rent_charged",
                       "total_rent_collected", "total_rent_missed"],
    "ev_daily_ledger": ["daily_cost", "provider_cost"],
    "provider_bills": ["bill_total"],
    "provider_bill_lines": ["their_amount", "our_amount", "discrepancy"],
    "payment_lines": ["amount"],
}


def main() -> int:
    db = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("PAYOUT_DB", "payout.db")
    if not os.path.exists(db):
        print(f"DB not found: {db}")
        return 1

    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE IF NOT EXISTS _schema_migrations "
                 "(name TEXT PRIMARY KEY, applied_at TEXT)")
    if conn.execute("SELECT 1 FROM _schema_migrations WHERE name='paise_money'").fetchone():
        print("Already migrated to paise — nothing to do.")
        return 0

    backup = f"{db}.pre_paise_backup"
    shutil.copy2(db, backup)
    print(f"Backed up -> {backup}")

    existing = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    total = 0
    for table, cols in MONEY.items():
        if table not in existing:
            continue
        tcols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for col in cols:
            if col not in tcols:
                continue
            n = conn.execute(
                f"UPDATE {table} SET {col} = CAST(ROUND({col} * 100) AS INTEGER) "
                f"WHERE {col} IS NOT NULL"
            ).rowcount
            total += n
            print(f"  {table}.{col}: {n} rows -> paise")

    conn.execute("INSERT INTO _schema_migrations (name, applied_at) VALUES (?,?)",
                 ("paise_money", datetime.now().isoformat()))
    conn.commit()
    conn.close()
    print(f"Done. {total} money cells converted. Backup at {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
