"""Missed-rent arrears + recovery.

EV rent that can't be deducted because a rider is absent from their deduction
company's payout accumulates in ev_arrears, separate from general dues, and is
clawed back from future payouts.

apply_settlement is the pure "collect everything due, then release the rest"
calculation (rent -> EV arrears -> general dues). record_missed_rent and
record_recovery write the audit trail and move the arrears tab.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date


@dataclass
class Settlement:
    rent_paid: float
    rent_short: float           # current rent the payout could not cover -> dues
    cod_paid: float             # COD recovered this cycle (both carryover + new)
    cod_short: float            # COD-pending NOT covered this cycle -> stays in COD-arrears
    arrears_recovered: float
    dues_cleared: float
    released: float             # amount actually paid out to the rider
    new_balance: float          # new general balance (<= 0; negative = dues)
    new_arrears: float          # new EV-rent arrears outstanding
    cod_carry_recovered: float = 0.0
    new_cod_outstanding: float = 0.0


def apply_settlement(
    payout: float, rent: float, prev_balance: float, arrears_outstanding: float,
    cod_due: float = 0.0, cod_outstanding: float = 0.0,
) -> Settlement:
    """Net a payout against rent, EV arrears, then dues.

    A negative gross payout (after the company's own deductions) is clamped to
    zero — riders are never billed for showing up — but the EV rent for the
    cycle still counts and rolls into dues if it can't be covered.

    COD-pending (``cod_due``, ``cod_outstanding``) is **not deducted** from
    the payout. It still arrives in the Settlement fields so callers and
    auditors can see how much was pending, but the math doesn't touch it —
    riders with non-zero COD are marked HOLD by the engine and their COD is
    collected outside the payout flow.

    Order of operations (highest priority first):
        rent → EV arrears → general dues → release.

    Rent comes first because EV rent is a per-cycle obligation. EV arrears are
    recovered ahead of general dues so EV back-rent never loses out (per
    DESIGN.md §6.4); whatever is left clears the rider's general carryforward.
    """
    payout = max(0.0, payout)
    cod_due = max(0.0, cod_due)
    cod_outstanding = max(0.0, cod_outstanding)
    pool = payout + max(0.0, prev_balance)
    general_dues = max(0.0, -prev_balance)

    rent_paid = min(pool, rent); pool -= rent_paid
    rent_short = rent - rent_paid

    arrears_recovered = min(pool, arrears_outstanding); pool -= arrears_recovered

    dues_cleared = min(pool, general_dues); pool -= dues_cleared

    released = pool
    new_general_dues = (general_dues - dues_cleared) + rent_short
    return Settlement(
        rent_paid=rent_paid,
        rent_short=rent_short,
        cod_paid=0.0,
        cod_short=cod_due,
        arrears_recovered=arrears_recovered,
        dues_cleared=dues_cleared,
        released=released,
        new_balance=-new_general_dues,
        new_arrears=arrears_outstanding - arrears_recovered,
        cod_carry_recovered=0.0,
        new_cod_outstanding=cod_outstanding,  # unchanged: COD doesn't move via the payout
    )


def get_arrears(conn: sqlite3.Connection, person_id: int):
    """Return (total_missed, total_recovered, outstanding)."""
    row = conn.execute(
        "SELECT total_missed, total_recovered, outstanding FROM ev_arrears WHERE person_id=?",
        (person_id,),
    ).fetchone()
    if not row:
        return (0.0, 0.0, 0.0)
    return (row["total_missed"], row["total_recovered"], row["outstanding"])


def _ensure_arrears(conn, person_id):
    conn.execute(
        "INSERT OR IGNORE INTO ev_arrears (person_id, total_missed, total_recovered, "
        "outstanding, last_updated) VALUES (?,0,0,0,?)",
        (person_id, date.today().isoformat()),
    )


def _gen_balance(conn, person_id):
    row = conn.execute("SELECT current_balance FROM balances WHERE person_id=?", (person_id,)).fetchone()
    return row["current_balance"] if row else 0.0


def _iso(d):
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def record_missed_rent(
    conn, person_id, amount, cycle_start, cycle_end, *,
    rider_id="", company="", created_by="engine", days=None,
):
    """Rider absent from payout: add EV rent to arrears and log RENT_MISSED."""
    if amount <= 0:
        return
    _ensure_arrears(conn, person_id)
    conn.execute(
        "UPDATE ev_arrears SET total_missed = total_missed + ?, "
        "outstanding = outstanding + ?, last_updated=? WHERE person_id=?",
        (amount, amount, date.today().isoformat(), person_id),
    )
    conn.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, days, remarks, created_by) "
        "VALUES (?,?,?,?,?,'RENT_MISSED',?,?,?,?,?)",
        (person_id, rider_id, company, _iso(cycle_start), _iso(cycle_end),
         -amount, _gen_balance(conn, person_id), days,
         "EV rent missed (absent from payout)", created_by),
    )


def record_recovery(
    conn, person_id, amount, cycle_start, cycle_end, *,
    rider_id="", company="", created_by="engine",
):
    """Claw arrears back from a payout: reduce arrears and log RENT_RECOVERED."""
    if amount <= 0:
        return 0.0
    _ensure_arrears(conn, person_id)
    conn.execute(
        "UPDATE ev_arrears SET total_recovered = total_recovered + ?, "
        "outstanding = outstanding - ?, last_updated=? WHERE person_id=?",
        (amount, amount, date.today().isoformat(), person_id),
    )
    conn.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, remarks, created_by) "
        "VALUES (?,?,?,?,?,'RENT_RECOVERED',?,?,?,?)",
        (person_id, rider_id, company, _iso(cycle_start), _iso(cycle_end),
         amount, _gen_balance(conn, person_id), "EV arrears recovered", created_by),
    )
    return amount


def get_cod_arrears(conn, person_id):
    """Return (cod_missed_total, cod_recovered_total, cod_outstanding)."""
    row = conn.execute(
        "SELECT cod_missed, cod_recovered, cod_outstanding FROM ev_arrears "
        "WHERE person_id=?", (person_id,),
    ).fetchone()
    if not row:
        return (0.0, 0.0, 0.0)
    return (row["cod_missed"], row["cod_recovered"], row["cod_outstanding"])


def record_cod_missed(
    conn, person_id, amount, cycle_start, cycle_end, *,
    rider_id="", company="", created_by="engine",
):
    """COD-pending the rider couldn't clear this cycle → COD-arrears tab."""
    if amount <= 0:
        return
    _ensure_arrears(conn, person_id)
    conn.execute(
        "UPDATE ev_arrears SET cod_missed = cod_missed + ?, "
        "cod_outstanding = cod_outstanding + ?, last_updated=? WHERE person_id=?",
        (amount, amount, date.today().isoformat(), person_id),
    )
    conn.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, remarks, created_by) "
        "VALUES (?,?,?,?,?,'COD_MISSED',?,?,?,?)",
        (person_id, rider_id, company, _iso(cycle_start), _iso(cycle_end),
         -amount, _gen_balance(conn, person_id),
         "COD pending (rolled into COD-arrears)", created_by),
    )


def record_cod_recovery(
    conn, person_id, amount, cycle_start, cycle_end, *,
    rider_id="", company="", created_by="engine",
):
    """Claw COD-arrears back from a payout: reduce cod_outstanding."""
    if amount <= 0:
        return 0.0
    _ensure_arrears(conn, person_id)
    conn.execute(
        "UPDATE ev_arrears SET cod_recovered = cod_recovered + ?, "
        "cod_outstanding = cod_outstanding - ?, last_updated=? WHERE person_id=?",
        (amount, amount, date.today().isoformat(), person_id),
    )
    conn.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, remarks, created_by) "
        "VALUES (?,?,?,?,?,'COD_RECOVERED',?,?,?,?)",
        (person_id, rider_id, company, _iso(cycle_start), _iso(cycle_end),
         amount, _gen_balance(conn, person_id), "COD arrears recovered", created_by),
    )
    return amount