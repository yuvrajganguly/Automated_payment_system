"""Diagnose money-scale consistency (paise vs rupees) across tables.

After the paise migration, EVERY money column should be integer paise. This
script checks whether ev_arrears / balances are on the same scale as the
ledger + transactions. If they're 100x smaller, those rows are still in
RUPEES — which makes the API (which divides by 100) show them 100x too small
(e.g. ₹952 arrears displays as 9.52).

Usage:
    python scripts/diagnose_money_scale.py            # uses ./payout.db
    python scripts/diagnose_money_scale.py path/to.db
"""
from __future__ import annotations

import sqlite3
import sys

db = sys.argv[1] if len(sys.argv) > 1 else "payout.db"
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row


def scalar(q):
    r = c.execute(q).fetchone()
    return (r[0] if r and r[0] is not None else 0)


print(f"\n=== Money-scale diagnostic for {db} ===\n")

ref = {
    "ev_models.weekly_rate (MAX)":     scalar("SELECT MAX(weekly_rate) FROM ev_models"),
    "ev_daily_ledger.daily_cost (MAX)": scalar("SELECT MAX(daily_cost) FROM ev_daily_ledger"),
    "transactions.amount (MAX abs)":   scalar("SELECT MAX(ABS(amount)) FROM transactions"),
    "ev_arrears.outstanding (MAX)":    scalar("SELECT MAX(outstanding) FROM ev_arrears"),
    "balances.current_balance (MAX abs)": scalar("SELECT MAX(ABS(current_balance)) FROM balances"),
}
for k, v in ref.items():
    print(f"  {k:38} = {v:,.2f}")

# A weekly EV rate is ~1,000-1,500 rupees. In paise that's ~100,000-150,000.
wr = ref["ev_models.weekly_rate (MAX)"]
unit = "PAISE" if wr >= 50_000 else "RUPEES"
print(f"\n  -> weekly_rate looks like it is stored in: {unit}")

# Cross-check: per person, ev_arrears.outstanding should equal the running
# (missed - recovered) from their transactions, IF both are the same scale.
print("\n=== Per-person cross-check (arrears vs the transactions that built it) ===")
print("  If 'ratio' ~1.0 -> consistent. If ~0.01 -> arrears is in RUPEES (bug).\n")
rows = c.execute(
    "SELECT a.person_id, a.outstanding, "
    "  COALESCE((SELECT SUM(-t.amount) FROM transactions t "
    "            WHERE t.person_id=a.person_id AND t.event_type='RENT_MISSED'),0) "
    "  - COALESCE((SELECT SUM(t.amount) FROM transactions t "
    "            WHERE t.person_id=a.person_id AND t.event_type IN ('RENT_RECOVERED','XC_RENT_RECOVERED')),0) "
    "  AS txn_based "
    "FROM ev_arrears a WHERE a.outstanding > 0 "
    "ORDER BY a.outstanding DESC LIMIT 8"
).fetchall()
for r in rows:
    out, txn = float(r["outstanding"]), float(r["txn_based"])
    ratio = (out / txn) if txn else float("nan")
    print(f"  pid {r['person_id']:>4}: arrears={out:>12,.2f}  txn_based={txn:>12,.2f}  ratio={ratio:.4f}")

print("\nVERDICT:")
print("  - ratios ~1.0  => arrears & transactions are the SAME scale (consistent).")
print("  - ratios ~0.01 => ev_arrears is in RUPEES while transactions are PAISE")
print("                    => run a targeted x100 migration on ev_arrears + balances.")
