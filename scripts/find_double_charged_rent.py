"""Find riders historically double-charged EV rent by the RENT_MISSED meter bug
(fixed in the engine going forward).

The bug: a missed-rent cycle left the meter behind, so a later overlapping
cycle re-billed the same days via a catch-up RENT *while* the arrears were
also recovered as cash. This scans committed transactions for that signature
and estimates the overcharge per person.

OUTPUT IS FOR REVIEW, NOT AUTO-CORRECTION. Verify a few by hand before issuing
any credit (post an ADJUSTMENT for the shown amount to make a rider whole).

Usage:  python scripts/find_double_charged_rent.py [path/to.db]
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import date

db = sys.argv[1] if len(sys.argv) > 1 else "payout.db"
c = sqlite3.connect(db)
c.row_factory = sqlite3.Row


def d(s: str) -> date:
    return date.fromisoformat(s)


def win_start(cycle_end: str, days: int) -> date:
    end = d(cycle_end)
    return date.fromordinal(end.toordinal() - (days - 1))


by_person: dict[int, list[dict]] = {}
for r in c.execute(
    "SELECT person_id, id, event_type, cycle_start, cycle_end, days, amount "
    "FROM transactions "
    "WHERE event_type IN ('RENT','RENT_MISSED','RENT_RECOVERED') ORDER BY id"
):
    by_person.setdefault(r["person_id"], []).append(dict(r))

rows = []
for pid, txns in by_person.items():
    missed = [t for t in txns if t["event_type"] == "RENT_MISSED"]
    rents = [t for t in txns if t["event_type"] == "RENT" and (t["days"] or 0) > 0]
    recovered = sum(t["amount"] for t in txns if t["event_type"] == "RENT_RECOVERED")
    if not missed or recovered <= 0:
        continue

    overcharge = 0
    incidents = []
    for m in missed:
        m_start, m_end = d(m["cycle_start"]), d(m["cycle_end"])
        m_amt = -m["amount"]
        for t in rents:
            t_end = d(t["cycle_end"])
            t_start = win_start(t["cycle_end"], t["days"])
            # A later catch-up RENT whose billed window reaches back into the
            # missed window = those missed days were re-billed.
            if t_end >= m_end and t_start <= m_end and t_end >= m_start and t_start <= m_start:
                overcharge += m_amt
                incidents.append(
                    f"missed {m['cycle_start']}..{m['cycle_end']} ({m_amt/100:.0f}) "
                    f"re-billed by RENT ending {t['cycle_end']} ({t['days']}d)"
                )
                break
    overcharge = min(overcharge, recovered)  # can't exceed what was clawed back
    if overcharge > 0:
        name = c.execute(
            "SELECT display_name FROM person_registry WHERE person_id=?", (pid,)
        ).fetchone()
        rows.append((pid, name["display_name"] if name else "?", overcharge, incidents))

rows.sort(key=lambda x: -x[2])
print(f"\n=== Potential EV-rent double-charges in {db} (FOR REVIEW) ===\n")
if not rows:
    print("  None found.")
else:
    print(f"  {'person':>7}  {'name':<22} {'overcharge (Rs.)':>16}")
    total = 0
    for pid, name, oc, _inc in rows:
        print(f"  {pid:>7}  {name[:22]:<22} {oc/100:>16,.2f}")
        total += oc
    print(f"  {'':>7}  {'TOTAL':<22} {total/100:>16,.2f}")
    print(f"\n  {len(rows)} rider(s) affected. Showing first incident each:")
    for pid, name, oc, inc in rows[:10]:
        print(f"    #{pid} {name}: {inc[0] if inc else ''}")
    print(
        "\n  To remediate (after review): post an ADJUSTMENT credit of the shown\n"
        "  amount per rider via the ledger, with a reason like 'EV-rent double-\n"
        "  charge correction'. Do NOT bulk-apply without spot-checking."
    )
c.close()
