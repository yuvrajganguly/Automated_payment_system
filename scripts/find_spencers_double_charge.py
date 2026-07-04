r"""Find riders double-charged by a stuck-meter catch-up (default: Spencer's).

The bug: if a rider's EV meter (rent_charged_through) was left behind (e.g. a
week was recorded RENT_MISSED under old behavior and didn't advance the meter),
the next cycle's engine "catches up" and bills a RENT covering more days than
the cycle actually spans. If that same run also RECOVERS the arrears for the
overlapping missed days, those days get billed twice.

This detector flags exactly that shape: a RENT whose ``days`` exceeds the cycle
span, where the same person+cycle also has RENT_RECOVERED covering (part of) the
excess. It is READ-ONLY.

    python scripts/find_spencers_double_charge.py \
        "postgresql://payout:payout@localhost:5432/payout"          # all Spencer's
    python scripts/find_spencers_double_charge.py "<url>" --company Myntra
    python scripts/find_spencers_double_charge.py "<url>" --all      # every company

Columns:
  billed        rent actually charged this cycle (covers `days_billed` days)
  correct_rent  what the cycle rent should be (cycle-span days only)
  recovered     arrears recovered in the same run
  OVERCHARGE    the duplicated amount = credit to refund the rider
"""
from __future__ import annotations

import sys
from datetime import date


def _span_days(cs: str, ce: str) -> int:
    a = date.fromisoformat(cs)
    b = date.fromisoformat(ce)
    return (b - a).days + 1


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        sys.exit(1)
    url = args[0]
    company = None if "--all" in sys.argv else "Spencer's"
    if "--company" in sys.argv:
        company = sys.argv[sys.argv.index("--company") + 1]

    import psycopg
    conn = psycopg.connect(url)

    where_co = "" if company is None else "AND t.company = %s"
    params = [] if company is None else [company]
    rents = conn.execute(
        f"""
        SELECT t.person_id, pr.display_name, t.company,
               t.cycle_start, t.cycle_end, t.amount, t.days
        FROM transactions t
        JOIN person_registry pr ON pr.person_id = t.person_id
        WHERE t.event_type = 'RENT' AND t.days IS NOT NULL {where_co}
        ORDER BY t.id DESC
        """,
        params,
    ).fetchall()

    flagged = []
    for pid, name, co, cs, ce, amount, days in rents:
        span = _span_days(cs, ce)
        if not days or days <= span:
            continue
        rent_paise = abs(int(amount))
        daily = rent_paise / days
        excess_days = days - span
        excess_paise = daily * excess_days
        rec = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM transactions "
            "WHERE person_id=%s AND cycle_start=%s AND cycle_end=%s "
            "AND event_type IN ('RENT_RECOVERED','XC_RENT_RECOVERED')",
            (pid, cs, ce),
        ).fetchone()[0]
        recovered = int(rec or 0)
        overcharge = min(recovered, round(excess_paise))
        if overcharge <= 0:
            continue
        flagged.append({
            "pid": pid, "name": name or "?", "co": co,
            "cycle": f"{cs}..{ce}",
            "days_billed": days, "span": span,
            "billed": rent_paise / 100.0,
            "correct_rent": round(daily * span / 100.0, 2),
            "recovered": recovered / 100.0,
            "overcharge": round(overcharge / 100.0, 2),
        })

    label = company or "ALL companies"
    print(f"\n=== Stuck-meter double-charges ({label}) ===\n")
    if not flagged:
        print("  None found.\n")
        return
    print(f"  {'pid':>5}  {'name':<22}  {'cycle':<24}  {'days':>4}/{'span':<4} "
          f"{'billed':>9} {'correct':>9} {'recovered':>10} {'OVERCHARGE':>11}")
    print("  " + "-" * 100)
    total = 0.0
    for f in sorted(flagged, key=lambda x: -x["overcharge"]):
        total += f["overcharge"]
        print(f"  {f['pid']:>5}  {f['name'][:22]:<22}  {f['cycle']:<24}  "
              f"{f['days_billed']:>4}/{f['span']:<4} {f['billed']:>9,.2f} "
              f"{f['correct_rent']:>9,.2f} {f['recovered']:>10,.2f} "
              f"{f['overcharge']:>11,.2f}")
    print("  " + "-" * 100)
    print(f"  {len(flagged)} rider(s); total overcharge to refund: "
          f"{total:,.2f}\n")
    print("  Fix: post a credit ADJUSTMENT of each rider's OVERCHARGE to their "
          "ledger.\n  (Their meter is now advanced, so it won't recur.)\n")


if __name__ == "__main__":
    main()
