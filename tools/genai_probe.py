"""Build a de-identified rent-explainer prompt for one person.

A probe, not a feature. It answers one question before any Gen AI code gets
written: can a small local model, given exactly the facts the rent engine
uses, reach the same conclusion the engine did?

It emits the prompt and nothing else, so the output can be piped straight into
``ollama run`` or pasted into a chat. Two properties matter and both are
enforced here rather than trusted:

  * No names, phones, Aadhaar, PAN or account numbers are read from the
    database at all. The person is "the rider" and EVs are relabelled EV-1,
    EV-2... in first-seen order, so even the fleet ids stay in-house. What
    the model sees is dates, day counts and rupees.
  * Money is rendered in rupees. Internally everything is paise; a model
    handed 129500 and asked about "rent" will narrate ₹129,500.

Usage (on the box, with DB_URL set):

    python -m tools.genai_probe --person 4417
    python -m tools.genai_probe --person 4417 --from 2026-08-01 | ollama run llama3.1:8b

``--answer`` additionally prints what the engine itself computes for the most
recent cycle, so the model's reply can be marked without opening the console.
"""

from __future__ import annotations

import argparse
import sys

RULES = """\
You are auditing an EV-rental ledger. Apply these rules exactly; do not invent
rules, and do not guess at facts you were not given.

1. Rent is a daily meter, not a monthly bill. Each billing cycle charges the
   days from the day AFTER `rent_charged_through` up to the cycle's end date.
2. The daily rate is the EV's weekly rate divided by 7.
3. The handover day and the return day are both FREE. An assignment is
   chargeable only over [handover_date + 1 .. returned_date - 1].
4. A rider may swap EVs mid-cycle. When two assignments overlap one cycle,
   the cycle's rent is the SUM of both legs, each clamped by rule 3. Each leg
   is charged at its own EV's rate.
5. Days inside a maintenance window for that EV are not charged.
6. The meter advances whether the day was paid (rider present) or missed to
   arrears (rider absent). A RENT_MISSED row means the day was billed to
   arrears, not that it was skipped.
7. Days behind the meter that no RENT or RENT_MISSED window ever covered are
   billed by the next cycle that processes the rider ("catch-up").

Answer in at most six sentences. State the number of chargeable days, which
assignment leg each day belongs to, and the rupee total. If the facts are
insufficient to decide, say so instead of estimating.
"""


def _r(paise: int | None) -> str:
    """Paise -> a rupee string the model can reason about."""
    return "-" if paise is None else f"Rs {paise / 100:,.2f}"


NARRATE = """\
You are explaining an EV-rental charge to the person who was billed. The
arithmetic below has already been done and verified — treat every number as
given and correct. Do NOT recompute, re-count days, or second-guess the
figures.

Your job is only to explain, in plain English, why the charge is what it is:
what the rider held, over which days, and why the days that were not charged
were not charged. Four sentences at most. Use the rupee figures exactly as
written.
"""


def build_narrate(conn, person_id: int, cs, ce) -> str:
    """The same case, but with the arithmetic already done.

    The counterpart to build(): where that one asks the model to reason from
    rules to a number, this one hands it the number and asks only for the
    sentence. If a small model can do this and not that, the feature is built
    this way round.
    """
    from payout.domain.rent import resolve_rent

    info = resolve_rent(conn, person_id, cs, ce)
    ev_alias: dict[str, str] = {}
    out = [NARRATE, "", "=== ALREADY COMPUTED ===", "", f"Cycle: {cs} to {ce}"]
    for leg in info.legs:
        ev_alias.setdefault(leg.ev_id, f"EV-{len(ev_alias) + 1}")
        out.append(
            f"  {ev_alias[leg.ev_id]}: charged {leg.days} days "
            f"({leg.rent_from} to {leg.rent_through}) at {_r(int(leg.weekly_rate / 7))}/day "
            f"= {_r(int(leg.rent))}"
        )
        if leg.returned_date:
            out.append(f"     returned {leg.returned_date} (return day not charged)")
        if leg.handover_date:
            out.append(f"     handed over {leg.handover_date} (handover day not charged)")
    out += [
        "",
        f"TOTAL CHARGED: {info.days} days = {_r(int(info.rent))}",
        "",
        "=== QUESTION ===",
        "",
        "Explain this charge to the rider.",
    ]
    return "\n".join(out)


def build(conn, person_id: int, since: str | None) -> str:
    ev_alias: dict[str, str] = {}

    def alias(ev_id: str) -> str:
        if ev_id not in ev_alias:
            ev_alias[ev_id] = f"EV-{len(ev_alias) + 1}"
        return ev_alias[ev_id]

    out: list[str] = [RULES, "", "=== FACTS ===", ""]

    legs = conn.execute(
        "SELECT a.assignment_id, a.ev_id, a.handover_date, a.returned_date, "
        "       a.rent_charged_through, m.weekly_rate "
        "FROM ev_assignments a "
        "JOIN ev_units u  ON u.ev_id = a.ev_id "
        "JOIN ev_models m ON m.model_id = u.model_id "
        "WHERE a.person_id = ? "
        "ORDER BY a.handover_date, a.assignment_id",
        (person_id,),
    ).fetchall()

    if not legs:
        return "No EV assignments for that person — nothing to explain."

    out.append("Assignments (one line per EV the rider has held):")
    for r in legs:
        ev = alias(r["ev_id"])
        weekly = r["weekly_rate"]
        out.append(
            f"  {ev}: handed over {r['handover_date']}, "
            f"returned {r['returned_date'] or 'still held'}, "
            f"rate {_r(weekly)}/week ({_r(round(weekly / 7))}/day), "
            f"billed through {r['rent_charged_through'] or 'never'}"
        )
    out.append("")

    maint = conn.execute(
        "SELECT ev_id, from_date, to_date FROM ev_maintenance "
        "WHERE ev_id IN (SELECT ev_id FROM ev_assignments WHERE person_id = ?) "
        "ORDER BY from_date",
        (person_id,),
    ).fetchall()
    out.append("Maintenance windows (rent-free days):")
    if maint:
        out += [
            f"  {alias(r['ev_id'])}: {r['from_date']} to {r['to_date'] or 'ongoing'}" for r in maint
        ]
    else:
        out.append("  none")
    out.append("")

    sql = (
        "SELECT cycle_start, cycle_end, event_type, amount, days, remarks "
        "FROM transactions WHERE person_id = ? "
        "AND event_type IN ('RENT','RENT_MISSED','RENT_RECOVERED','RENT_REVERSAL',"
        "'RENT_WAIVED','DEPOSIT_APPLIED','EV_SWAP') "
    )
    params: list[object] = [person_id]
    if since:
        sql += "AND cycle_end >= ? "
        params.append(since)
    sql += "ORDER BY cycle_start, id"

    out.append("Rent events already on the ledger (oldest first):")
    rows = conn.execute(sql, tuple(params)).fetchall()
    for r in rows:
        out.append(
            f"  {r['cycle_start']}..{r['cycle_end']}  {r['event_type']:<16} "
            f"{_r(r['amount']):>14}  days={r['days'] if r['days'] is not None else '-'}"
            + (f"  ({r['remarks']})" if r["remarks"] else "")
        )
    if not rows:
        out.append("  none")

    out += [
        "",
        "=== QUESTION ===",
        "",
        "Walk through this rider's rent for the most recent cycle above. "
        "Is the amount charged correct under the rules? If it is wrong, say "
        "which rule was misapplied and what the correct figure is.",
    ]
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--person", type=int, required=True, help="person_id to probe")
    ap.add_argument("--from", dest="since", help="only ledger rows ending on/after YYYY-MM-DD")
    ap.add_argument("--answer", action="store_true", help="also print the engine's own figure")
    ap.add_argument(
        "--narrate",
        nargs=2,
        metavar=("CYCLE_START", "CYCLE_END"),
        help="emit the narrate-mode prompt for this cycle instead of the reasoning one",
    )
    args = ap.parse_args()

    from payout.db.connection import get_connection

    conn = get_connection()
    try:
        if args.narrate:
            from datetime import date as _d

            print(
                build_narrate(
                    conn,
                    args.person,
                    _d.fromisoformat(args.narrate[0]),
                    _d.fromisoformat(args.narrate[1]),
                )
            )
        else:
            print(build(conn, args.person, args.since))
        if args.answer:
            from datetime import date

            from payout.domain.rent import resolve_rent

            last = conn.execute(
                "SELECT cycle_start, cycle_end FROM transactions "
                "WHERE person_id = ? AND event_type IN ('RENT','RENT_MISSED') "
                "ORDER BY cycle_start DESC LIMIT 1",
                (args.person,),
            ).fetchone()
            if last:
                cs = date.fromisoformat(last["cycle_start"])
                ce = date.fromisoformat(last["cycle_end"])
                info = resolve_rent(conn, args.person, cs, ce)
                print(
                    f"\n=== ENGINE (not for the model) ===\n"
                    f"{cs}..{ce}: {info.days} days, {_r(int(info.rent))}",
                    file=sys.stderr,
                )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
