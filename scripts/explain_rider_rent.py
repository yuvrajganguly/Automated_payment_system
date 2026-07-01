"""Explain a rider's recent rent activity — why a payout showed a given rent.

Prints every rent-related ledger row (RENT charge, RENT_COLLECTED,
RENT_RECOVERED, RENT_MISSED) for a rider over the last few cycles, with the
cycle window, company, and amount in rupees, plus the EV meter state. Use it to
answer "why did X have rent collected 2500 this week?".

Read-only. Makes no changes.

Usage:
    python scripts/explain_rider_rent.py "REDACTED RIDER" C:\payout_data\payout.db
    python scripts/explain_rider_rent.py "Subrata" C:\payout_data\payout.db --limit 40
"""
from __future__ import annotations

import sqlite3
import sys

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if not args:
    print('Usage: python scripts/explain_rider_rent.py "<name>" [db_path] [--limit N]')
    sys.exit(1)
name = args[0]
db_path = args[1] if len(args) > 1 else "payout.db"
limit = 30
if "--limit" in sys.argv:
    limit = int(sys.argv[sys.argv.index("--limit") + 1])

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row


def rupees(paise):
    return f"{(paise or 0) / 100.0:,.2f}"


people = conn.execute(
    "SELECT person_id, display_name FROM person_registry "
    "WHERE display_name LIKE ? ORDER BY display_name",
    (f"%{name}%",),
).fetchall()

if not people:
    print(f"\n  No rider matching '{name}'.\n")
    sys.exit(0)
if len(people) > 1:
    print(f"\n  Multiple riders match '{name}':")
    for p in people:
        print(f"    pid {p['person_id']:>5}  {p['display_name']}")
    print("  Re-run with a more specific name.\n")
    sys.exit(0)

pid = people[0]["person_id"]
print(f"\n=== Rent activity for {people[0]['display_name']} (pid {pid}) ===\n")

# EV meter state
asg = conn.execute(
    "SELECT assignment_id, rent_charged_through, returned_date "
    "FROM ev_assignments WHERE person_id=? ORDER BY assignment_id DESC",
    (pid,),
).fetchall()
for a in asg:
    state = "OPEN" if a["returned_date"] is None else f"returned {a['returned_date']}"
    print(f"  assignment {a['assignment_id']}: rent_charged_through="
          f"{a['rent_charged_through'] or '(none)'}  [{state}]")

arr = conn.execute(
    "SELECT outstanding, total_missed, total_recovered "
    "FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()
if arr:
    print(f"  ev_arrears: outstanding={rupees(arr['outstanding'])}  "
          f"missed={rupees(arr['total_missed'])}  "
          f"recovered={rupees(arr['total_recovered'])}")

bal = conn.execute(
    "SELECT current_balance FROM balances WHERE person_id=?", (pid,)).fetchone()
if bal:
    print(f"  balance: {rupees(bal['current_balance'])}")

print(f"\n  Last {limit} rent-related ledger rows (newest first):\n")
print(f"  {'id':>6}  {'event':<16}  {'cycle':<25}  {'company':<12}  {'amount':>12}")
print(f"  {'-'*6}  {'-'*16}  {'-'*25}  {'-'*12}  {'-'*12}")
rows = conn.execute(
    """
    SELECT id, event_type, cycle_start, cycle_end, company, amount, remarks
    FROM transactions
    WHERE person_id=?
      AND event_type IN ('RENT','RENT_COLLECTED','RENT_RECOVERED',
                         'RENT_MISSED','XC_RENT','XC_RENT_RECOVERED')
    ORDER BY id DESC LIMIT ?
    """,
    (pid, limit),
).fetchall()
for r in rows:
    cyc = f"{r['cycle_start'] or '?'}..{r['cycle_end'] or '?'}"
    print(f"  {r['id']:>6}  {r['event_type']:<16}  {cyc:<25}  "
          f"{(r['company'] or '')[:12]:<12}  {rupees(r['amount']):>12}"
          + (f"   {r['remarks']}" if r["remarks"] else ""))
print()
conn.close()
