r"""Find riders charged twice for carried dues (the 2026-11-24 bug). READ-ONLY.

The bug: a cash payment through POST /ledger/rent-payment (Person page "Record
rent payment", and every row of the hub's collection sheet upload) paid EV
arrears first and booked the REST as RENT_COLLECTED without touching the
balance. When the rider was paying their Total Dues (arrears + carried dues),
the carried-dues part stayed on the balance, and the next payout cleared it
again as "Dues Cleared".

For every manual RENT_COLLECTED row this prints how much of it was NOT paying
for days (no ev_daily_ledger row cites it) while the balance was negative at
the time — the cash that should have cleared dues — and how much of that the
later payouts then took again.

    python scripts/find_cash_dues_double_charge.py "postgresql://payout:payout@localhost:5432/payout"
    python scripts/find_cash_dues_double_charge.py path/to/payout.db

Columns:
  cash        the RENT_COLLECTED amount (₹)
  for_days    the part that paid for EV days (a real advance payment)
  dues_then   carried dues on the balance when the cash came in
  SHOULD_CLR  cash that should have cleared dues = min(cash - for_days, dues_then)
  retaken     Dues Cleared from payouts after that payment (capped at SHOULD_CLR)

Fix per rider: a credit ADJUSTMENT of SHOULD_CLR ("Cash paid on <date> did not
clear carried dues — 2026-11-24 fix"). Where `retaken` is 0 the dues are still
on the books and the credit cancels them; where it is > 0 the payout already
took them and the credit pays it back in the next release.
"""

from __future__ import annotations

import sqlite3
import sys


def _connect(target: str):
    if target.startswith("postgres"):
        import psycopg
        from psycopg.rows import dict_row

        return psycopg.connect(target, row_factory=dict_row), "%s"
    conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn, "?"


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    conn, ph = _connect(args[0])
    rows = conn.execute(
        "SELECT t.id, t.person_id, pr.display_name AS name, t.amount, t.balance_after, "
        "       t.created_at, "
        "       COALESCE((SELECT SUM(d.daily_cost) FROM ev_daily_ledger d "
        "                 WHERE d.cycle_event_id = t.id OR d.recovery_event_id = t.id), 0) "
        "         AS for_days "
        "FROM transactions t JOIN person_registry pr ON pr.person_id = t.person_id "
        "WHERE t.event_type = 'RENT_COLLECTED' AND t.remarks LIKE 'manual rent payment%' "
        "  AND t.balance_after < 0 "
        "ORDER BY t.person_id, t.id"
    ).fetchall()

    found = []
    for r in rows:
        cash = int(r["amount"])
        spare = max(0, cash - int(r["for_days"] or 0))
        should = min(spare, -int(r["balance_after"]))
        if should <= 0:
            continue
        later = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM transactions "
            f"WHERE person_id = {ph} AND id > {ph} AND event_type = 'DUES_CLEARED' "
            "  AND created_by = 'engine'",
            (r["person_id"], r["id"]),
        ).fetchone()["s"]
        found.append((r, cash, int(r["for_days"] or 0), -int(r["balance_after"]), should,
                      min(int(later or 0), should)))

    print("\n=== Cash that did not clear carried dues ===\n")
    if not found:
        print("  None found.\n")
        return
    print(f"  {'pid':>5}  {'name':<22} {'paid on':<11} {'cash':>9} {'for_days':>9} "
          f"{'dues_then':>10} {'SHOULD_CLR':>11} {'retaken':>9}")
    print("  " + "-" * 96)
    tot = tot_re = 0
    for r, cash, days, dues, should, re in found:
        tot += should
        tot_re += re
        print(f"  {r['person_id']:>5}  {str(r['name'] or '?')[:22]:<22} "
              f"{str(r['created_at'])[:10]:<11} {cash / 100:>9,.2f} {days / 100:>9,.2f} "
              f"{dues / 100:>10,.2f} {should / 100:>11,.2f} {re / 100:>9,.2f}")
    print("  " + "-" * 96)
    print(f"  {len(found)} payment(s); to credit back {tot / 100:,.2f} "
          f"(of which {tot_re / 100:,.2f} was already taken again by a payout)\n")


if __name__ == "__main__":
    main()
