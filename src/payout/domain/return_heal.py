"""Backdated EV return — automatic reversal of rent charged after the fact.

The operational reality: riders hand EVs back and the office only hears about
it days or weeks later, usually mid payout-processing. By then the engine has
kept charging rent for days the rider no longer had the vehicle — deducted
from payouts, piled into arrears, or rolled into dues — and every one of those
charges used to be undone by hand.

``heal_backdated_return`` reverses them mechanically, from the day-level
ledger, the moment a return (or take-back-to-spare) is recorded with a past
date. The transactions log stays append-only: history is corrected with new
offsetting rows, never edited.

Per wrongly-charged day (``ev_daily_ledger`` rows on/after the return date):

===========  ==============================================================
status       what actually happened, and the reversal
===========  ==============================================================
billed       rider paid via a payout deduction (or manual rent payment)
             -> refund: credit their balance (ADJUSTMENT +amount)
recovered    day was missed, then paid via a later recovery
             -> refund likewise; the arrears totals (missed & recovered)
             are both wound back so lifetime stats don't overstate
missed       nobody paid; the debt sits in ev_arrears
             -> write it off: outstanding shrinks (RENT_REVERSAL row);
             any slice of the debt already settled by other means is
             refunded instead
pending /    charged by no event yet — nothing to reverse
NULL
===========  ==============================================================

Then the ledger itself is rewritten (return day becomes ``return_free``;
later days are deleted for a retired unit, or become ``unassigned`` for a
spare — we still owe the provider for a spare we hold, not for a unit we
gave back), and the assignment's rent meter is rewound. If the refund
leaves the rider holding both a credit and remaining arrears, the standard
credit-vs-arrears offset runs (same rule as everywhere else).
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from payout.domain.arrears import settle_arrears_from_credit


def _iso(d: Any) -> str:
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def heal_backdated_return(
    conn: Any,
    *,
    assignment_id: int,
    retire: bool,
    created_by: str,
) -> dict:
    """Reverse rent charged on/after the (already saved) returned_date.

    Call AFTER ``ev_assignments.returned_date`` has been set. ``retire`` is
    True for a unit given back to the provider (ledger days after the return
    are deleted — we owe nothing), False for take-back-to-spare (days become
    ``unassigned`` — provider cost still accrues to us).

    Returns a summary dict (paise): refunded, arrears_written_off,
    days_reversed, plus the offset applied afterwards, if any. All zeros when
    the return date is today/future or nothing was ever charged past it.
    """
    a = conn.execute(
        "SELECT person_id, ev_id, returned_date, rent_charged_through "
        "FROM ev_assignments WHERE assignment_id=?",
        (assignment_id,),
    ).fetchone()
    if not a or not a["returned_date"]:
        return _zero()
    person_id, ev_id = a["person_id"], a["ev_id"]
    ret = date.fromisoformat(str(a["returned_date"]))

    rows = conn.execute(
        "SELECT day, daily_cost, billing_status FROM ev_daily_ledger "
        "WHERE ev_id=? AND assigned_person_id=? AND day >= ? ORDER BY day",
        (ev_id, person_id, ret.isoformat()),
    ).fetchall()

    refund = 0  # paise the rider actually paid for days they didn't have the EV
    writeoff_target = 0  # missed-day paise to remove from arrears outstanding
    missed_dec = 0  # lifetime total_missed to wind back
    recovered_dec = 0  # lifetime total_recovered to wind back
    charged_days: list[str] = []
    for r in rows:
        dc = int(r["daily_cost"] or 0)
        status = r["billing_status"]
        if dc <= 0 or status not in ("billed", "recovered", "missed"):
            continue
        charged_days.append(str(r["day"]))
        if status == "billed":
            refund += dc
        elif status == "recovered":
            refund += dc
            missed_dec += dc
            recovered_dec += dc
        else:  # missed
            writeoff_target += dc
            missed_dec += dc

    # ── arrears write-off (clamped to what is still outstanding) ─────────────
    arrears_written_off = 0
    if writeoff_target or missed_dec or recovered_dec:
        ar = conn.execute(
            "SELECT total_missed, total_recovered, outstanding FROM ev_arrears WHERE person_id=?",
            (person_id,),
        ).fetchone()
        if ar:
            outstanding = int(ar["outstanding"])
            arrears_written_off = min(writeoff_target, max(0, outstanding))
            # A missed slice already settled some other way (manual adjustment)
            # means the rider effectively paid it — refund the difference.
            refund += writeoff_target - arrears_written_off
            conn.execute(
                "UPDATE ev_arrears SET "
                "  total_missed=?, total_recovered=?, outstanding=?, last_updated=? "
                "WHERE person_id=?",
                (
                    max(0, int(ar["total_missed"]) - missed_dec),
                    max(0, int(ar["total_recovered"]) - recovered_dec),
                    outstanding - arrears_written_off,
                    date.today().isoformat(),
                    person_id,
                ),
            )
        else:
            # No arrears row at all: the debt was cleared elsewhere -> refund.
            refund += writeoff_target

    span = f"{charged_days[0]}..{charged_days[-1]}" if charged_days else _iso(ret)
    first = charged_days[0] if charged_days else _iso(ret)
    last = charged_days[-1] if charged_days else _iso(ret)

    if arrears_written_off > 0:
        bal = conn.execute(
            "SELECT current_balance FROM balances WHERE person_id=?", (person_id,)
        ).fetchone()
        conn.execute(
            "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
            "event_type, amount, balance_after, days, remarks, created_by) "
            "VALUES (?,?,?,?,?,'RENT_REVERSAL',?,?,?,?,?)",
            (
                person_id,
                "",
                "",
                first,
                last,
                arrears_written_off,
                bal["current_balance"] if bal else 0,
                len(charged_days),
                f"Arrears written off — EV {ev_id} returned {_iso(ret)}, "
                f"rent wrongly missed {span}",
                created_by,
            ),
        )

    if refund > 0:
        brow = conn.execute(
            "SELECT current_balance FROM balances WHERE person_id=?", (person_id,)
        ).fetchone()
        new_balance = (int(brow["current_balance"]) if brow else 0) + refund
        conn.execute(
            "INSERT INTO balances (person_id, current_balance, last_updated) VALUES (?,?,?) "
            "ON CONFLICT(person_id) DO UPDATE SET current_balance=excluded.current_balance, "
            "last_updated=excluded.last_updated",
            (person_id, new_balance, date.today().isoformat()),
        )
        conn.execute(
            "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
            "event_type, amount, balance_after, days, remarks, created_by) "
            "VALUES (?,?,?,?,?,'ADJUSTMENT',?,?,?,?,?)",
            (
                person_id,
                "",
                "",
                first,
                last,
                refund,
                new_balance,
                len(charged_days),
                f"Refund — EV {ev_id} returned {_iso(ret)}, rent paid for {span} reversed",
                created_by,
            ),
        )

    # ── rewrite the ledger to reflect the true calendar ──────────────────────
    # Return day itself: free, unit still in hand that morning.
    conn.execute(
        "UPDATE ev_daily_ledger SET state='return_free', daily_cost=0, "
        "  billing_status=NULL, cycle_event_id=NULL, recovery_event_id=NULL, "
        "  last_updated=datetime('now') "
        "WHERE ev_id=? AND assigned_person_id=? AND day=?",
        (ev_id, person_id, ret.isoformat()),
    )
    if retire:
        conn.execute(
            "DELETE FROM ev_daily_ledger WHERE ev_id=? AND assigned_person_id=? AND day > ?",
            (ev_id, person_id, ret.isoformat()),
        )
    else:
        conn.execute(
            "UPDATE ev_daily_ledger SET state='unassigned', assigned_person_id=NULL, "
            "  daily_cost=0, billing_status=NULL, cycle_event_id=NULL, "
            "  recovery_event_id=NULL, last_updated=datetime('now') "
            "WHERE ev_id=? AND assigned_person_id=? AND day > ?",
            (ev_id, person_id, ret.isoformat()),
        )

    # ── rewind the rent meter ────────────────────────────────────────────────
    cap = (ret - timedelta(days=1)).isoformat()
    ct = a["rent_charged_through"]
    if ct and str(ct) > cap:
        conn.execute(
            "UPDATE ev_assignments SET rent_charged_through=? WHERE assignment_id=?",
            (cap, assignment_id),
        )

    # ── standard credit-vs-arrears offset, if the refund created an overlap ──
    offset = settle_arrears_from_credit(conn, person_id, created_by=created_by)

    return {
        "refunded": refund,
        "arrears_written_off": arrears_written_off,
        "days_reversed": len(charged_days),
        "offset_applied": offset,
    }


def _zero() -> dict:
    return {"refunded": 0, "arrears_written_off": 0, "days_reversed": 0, "offset_applied": 0}
