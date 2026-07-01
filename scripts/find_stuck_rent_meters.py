"""Find EV rent meters that are stuck behind a rider's paid-through date.

Background
----------
Each open EV assignment carries a "continuity meter", ``rent_charged_through``:
the last day the automated engine has billed. Rent is charged from the day
*after* it. A bug in the manual rent-payment endpoint only advanced this meter
when the payment landed on the *current* cycle (RENT_COLLECTED) — a payment
that cleared *arrears* (RENT_RECOVERED, i.e. previously-missed days) left the
meter stuck, so the engine would re-charge those already-paid days.

The endpoint is now fixed, but riders who paid *before* the fix still have a
stuck meter. This script lists every such rider so you can advance them in one
pass.

A meter is "stuck" when the latest cycle_end among that rider's RENT_COLLECTED
/ RENT_RECOVERED rows (the last window they actually paid for) is *after* their
current ``rent_charged_through``.

Usage
-----
    # read-only — just list who is stuck (SAFE, makes no changes):
    python scripts/find_stuck_rent_meters.py C:\payout_data\payout.db

    # apply the fix — advance each stuck meter forward to its paid-through
    # date. Makes a timestamped backup copy of the DB first.
    python scripts/find_stuck_rent_meters.py C:\payout_data\payout.db --fix

Only ever advances a meter FORWARD (never backward), so it is idempotent and
cannot un-bill a day.

IMPORTANT: run this with the backend STOPPED (no other process writing the DB),
and point it at the real DB path — NOT a copy on a cloud-synced folder.
"""
from __future__ import annotations

import shutil
import sqlite3
import sys
from datetime import datetime

FIX = "--fix" in sys.argv
args = [a for a in sys.argv[1:] if not a.startswith("--")]
db_path = args[0] if args else "payout.db"

conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

# Latest window each rider has actually paid for (collected or recovered),
# per open assignment, compared against the meter.
rows = conn.execute(
    """
    SELECT ea.assignment_id,
           ea.person_id,
           ea.rent_charged_through            AS meter,
           COALESCE(pr.display_name, '?')     AS name,
           MAX(t.cycle_end)                   AS paid_through
    FROM ev_assignments ea
    JOIN transactions t
      ON t.person_id = ea.person_id
     AND t.event_type IN ('RENT_COLLECTED', 'RENT_RECOVERED')
     AND t.cycle_end IS NOT NULL
     AND t.cycle_end <> ''
    LEFT JOIN person_registry pr ON pr.person_id = ea.person_id
    WHERE ea.returned_date IS NULL
    GROUP BY ea.assignment_id
    HAVING ea.rent_charged_through IS NULL
        OR ea.rent_charged_through = ''
        OR MAX(t.cycle_end) > ea.rent_charged_through
    ORDER BY name
    """
).fetchall()

print(f"\n=== Stuck EV rent meters in {db_path} ===\n")
if not rows:
    print("  None. Every open assignment's meter is at or ahead of its "
          "paid-through date.\n")
    conn.close()
    sys.exit(0)

print(f"  {'pid':>5}  {'name':<24}  {'meter (now)':<12}  {'paid through':<12}")
print(f"  {'-'*5}  {'-'*24}  {'-'*12}  {'-'*12}")
for r in rows:
    print(f"  {r['person_id']:>5}  {r['name'][:24]:<24}  "
          f"{(r['meter'] or '(none)'):<12}  {r['paid_through']:<12}")
print(f"\n  {len(rows)} assignment(s) stuck.\n")

if not FIX:
    print("  Read-only run — nothing changed. Re-run with --fix to advance "
          "these meters\n  forward to their paid-through date (a DB backup is "
          "made first).\n")
    conn.close()
    sys.exit(0)

# --- apply the fix ---
stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
backup = f"{db_path}.stuck_meter_backup_{stamp}"
shutil.copy(db_path, backup)
print(f"  Backup written: {backup}")

for r in rows:
    conn.execute(
        "UPDATE ev_assignments SET rent_charged_through=? WHERE assignment_id=?",
        (r["paid_through"], r["assignment_id"]),
    )
conn.commit()
print(f"  Advanced {len(rows)} meter(s) forward to their paid-through date.\n")
conn.close()
