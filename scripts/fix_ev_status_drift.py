r"""Find (and optionally fix) EVs whose ev_units.status disagrees with reality.

The unit status should follow the facts:
  * open assignment + not in maintenance  -> 'in_use'
  * open assignment + open maintenance     -> 'maintenance'
  * no open assignment, status is 'in_use' -> stale; should be 'spare'
  * no open assignment, status 'maintenance' w/ no open window -> 'spare'
'spare' vs 'returned' for an idle EV is a human decision, so those are left alone.

Read-only by default; pass --fix to apply. Backend-aware:

    python scripts/fix_ev_status_drift.py "postgresql://payout:payout@localhost:5432/payout"
    python scripts/fix_ev_status_drift.py "<url>" --fix
"""
from __future__ import annotations

import os
import sys

args = [a for a in sys.argv[1:] if not a.startswith("--")]
if not args:
    print(__doc__)
    sys.exit(1)
db = args[0]
FIX = "--fix" in sys.argv
if db.startswith("postgres://") or db.startswith("postgresql://"):
    os.environ["PAYOUT_DB_URL"] = db
else:
    os.environ["PAYOUT_DB"] = db

from payout.db import get_connection  # noqa: E402


def expected_status(current, has_assignment, in_maint):
    if has_assignment:
        return "maintenance" if in_maint else "in_use"
    # idle EV
    if current == "in_use":
        return "spare"           # was held, assignment closed w/o resetting
    if current == "maintenance" and not in_maint:
        return "spare"
    return current               # spare / returned: leave as-is


def main():
    conn = get_connection()
    rows = conn.execute(
        "SELECT u.ev_id, u.status, "
        "       a.person_id, pr.display_name AS holder, "
        "       (SELECT 1 FROM ev_maintenance mm "
        "          WHERE mm.ev_id=u.ev_id AND mm.to_date IS NULL LIMIT 1) AS in_maint "
        "FROM ev_units u "
        "LEFT JOIN ev_assignments a ON a.ev_id=u.ev_id AND a.returned_date IS NULL "
        "LEFT JOIN person_registry pr ON pr.person_id=a.person_id "
        "ORDER BY u.ev_id"
    ).fetchall()

    drift = []
    for r in rows:
        has = r["person_id"] is not None
        exp = expected_status(r["status"], has, bool(r["in_maint"]))
        if exp != r["status"]:
            drift.append((r["ev_id"], r["status"], exp, r["holder"]))

    print("\n=== EV status drift ===\n")
    if not drift:
        print("  None — every EV's status matches its assignment/maintenance state.\n")
        conn.close()
        return
    print(f"  {'ev_id':<12} {'current':<12} {'should be':<12} holder")
    print("  " + "-" * 56)
    for ev, cur, exp, holder in drift:
        print(f"  {ev:<12} {cur:<12} {exp:<12} {holder or '-'}")
    print(f"\n  {len(drift)} EV(s) drifted.\n")

    if not FIX:
        print("  Read-only. Re-run with --fix to correct them.\n")
        conn.close()
        return
    for ev, _cur, exp, _h in drift:
        conn.execute("UPDATE ev_units SET status=? WHERE ev_id=?", (exp, ev))
    conn.commit()
    conn.close()
    print(f"  Fixed {len(drift)} EV status value(s).\n")


if __name__ == "__main__":
    main()
