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
    rent_short: float  # current rent the payout could not cover -> dues
    cod_paid: float  # COD recovered this cycle (both carryover + new)
    cod_short: float  # COD-pending NOT covered this cycle -> stays in COD-arrears
    arrears_recovered: float
    dues_cleared: float
    released: float  # amount actually paid out to the rider
    new_balance: float  # new general balance (<= 0; negative = dues)
    new_arrears: float  # new EV-rent arrears outstanding
    cod_carry_recovered: float = 0.0
    new_cod_outstanding: float = 0.0


def apply_settlement(
    payout: float,
    rent: float,
    prev_balance: float,
    arrears_outstanding: float,
    cod_due: float = 0.0,
    cod_outstanding: float = 0.0,
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

    rent_paid = min(pool, rent)
    pool -= rent_paid
    rent_short = rent - rent_paid

    arrears_recovered = min(pool, arrears_outstanding)
    pool -= arrears_recovered

    dues_cleared = min(pool, general_dues)
    pool -= dues_cleared

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
    row = conn.execute(
        "SELECT current_balance FROM balances WHERE person_id=?", (person_id,)
    ).fetchone()
    return row["current_balance"] if row else 0.0


def _iso(d):
    return d.isoformat() if hasattr(d, "isoformat") else str(d)


def record_missed_rent(
    conn,
    person_id,
    amount,
    cycle_start,
    cycle_end,
    *,
    rider_id="",
    company="",
    created_by="engine",
    days=None,
    remarks=None,
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
        (
            person_id,
            rider_id,
            company,
            _iso(cycle_start),
            _iso(cycle_end),
            -amount,
            _gen_balance(conn, person_id),
            days,
            remarks or "EV rent missed (absent from payout)",
            created_by,
        ),
    )


def record_recovery(
    conn,
    person_id,
    amount,
    cycle_start,
    cycle_end,
    *,
    rider_id="",
    company="",
    created_by="engine",
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
        (
            person_id,
            rider_id,
            company,
            _iso(cycle_start),
            _iso(cycle_end),
            amount,
            _gen_balance(conn, person_id),
            "EV arrears recovered",
            created_by,
        ),
    )
    return amount


def settle_arrears_from_credit(conn, person_id, *, created_by, reason=None):
    """Use a positive general balance to pay down EV-rent arrears.

    A rider can end up with a credit (manual adjustment, COD clearance, a
    failed-transfer refund) while still carrying EV arrears. On the books they
    owed nothing net, but both sides sat there forever if no payout cycle ever
    ran for them again — the Arrears view showed a debt that was already
    covered. This settles the overlap immediately with a proper audit trail:
    an ADJUSTMENT debiting the credit and a RENT_RECOVERED reducing arrears
    (with the daily ledger healed like any other recovery).

    Returns the paise settled (0 when there is no overlap).
    """
    balance = _gen_balance(conn, person_id) or 0
    _, _, outstanding = get_arrears(conn, person_id)
    amount = int(min(max(0, balance), max(0, outstanding or 0)))
    if amount <= 0:
        return 0
    today = date.today()
    new_balance = balance - amount
    conn.execute(
        "UPDATE balances SET current_balance=?, last_updated=? WHERE person_id=?",
        (new_balance, today.isoformat(), person_id),
    )
    conn.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, remarks, created_by) "
        "VALUES (?,?,?,?,?,'ADJUSTMENT',?,?,?,?)",
        (
            person_id,
            "",
            "",
            today.isoformat(),
            today.isoformat(),
            -amount,
            new_balance,
            reason or "Credit balance applied to EV rent arrears",
            created_by,
        ),
    )
    record_recovery(conn, person_id, amount, today, today, created_by=created_by)
    rec = conn.execute(
        "SELECT id FROM transactions WHERE person_id=? AND event_type='RENT_RECOVERED' "
        "ORDER BY id DESC LIMIT 1",
        (person_id,),
    ).fetchone()
    if rec:
        from payout.domain.ev_daily import attribute_recovery

        attribute_recovery(conn, person_id=person_id, recovery_event_id=rec["id"], amount=amount)
    return amount


def get_cod_arrears(conn, person_id):
    """Return (cod_missed_total, cod_recovered_total, cod_outstanding)."""
    row = conn.execute(
        "SELECT cod_missed, cod_recovered, cod_outstanding FROM ev_arrears WHERE person_id=?",
        (person_id,),
    ).fetchone()
    if not row:
        return (0.0, 0.0, 0.0)
    return (row["cod_missed"], row["cod_recovered"], row["cod_outstanding"])


def record_cod_missed(
    conn,
    person_id,
    amount,
    cycle_start,
    cycle_end,
    *,
    rider_id="",
    company="",
    created_by="engine",
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
        (
            person_id,
            rider_id,
            company,
            _iso(cycle_start),
            _iso(cycle_end),
            -amount,
            _gen_balance(conn, person_id),
            "COD pending (rolled into COD-arrears)",
            created_by,
        ),
    )


def record_cod_recovery(
    conn,
    person_id,
    amount,
    cycle_start,
    cycle_end,
    *,
    rider_id="",
    company="",
    created_by="engine",
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
        (
            person_id,
            rider_id,
            company,
            _iso(cycle_start),
            _iso(cycle_end),
            amount,
            _gen_balance(conn, person_id),
            "COD arrears recovered",
            created_by,
        ),
    )
    return amount


def settle_from_deposit(conn, person_id, *, created_by, ev_id=None, cap=None):
    """Apply the rider's security deposit against what they owe, when their
    EV is closed (returned / retired / taken back as spare).

    Up to ``cap`` paise (default ``config.EV_DEPOSIT_PAISE``, ₹2,700) is
    removed from the rider's debt — EV back-rent arrears first, then general
    dues (negative balance). Nothing beyond the debt is credited: whatever is
    left of the deposit stays outside the books until damage charges are
    specified (future feature — settle manually for now).

    Every rupee applied gets a DEPOSIT_APPLIED transaction, and recovered
    arrears heal the day-ledger's missed days like any other recovery.
    Returns the total paise applied.
    """
    from payout.config import EV_DEPOSIT_PAISE
    from payout.domain.ev_daily import attribute_recovery

    remaining = int(EV_DEPOSIT_PAISE if cap is None else cap)
    if remaining <= 0:
        return 0
    today = date.today().isoformat()
    tag = f" after closing EV {ev_id}" if ev_id else " after closing EV"
    applied = 0

    # 1) EV back-rent arrears.
    row = conn.execute(
        "SELECT outstanding FROM ev_arrears WHERE person_id=?", (person_id,)
    ).fetchone()
    out = int(row["outstanding"]) if row else 0
    take = min(remaining, max(0, out))
    if take > 0:
        conn.execute(
            "UPDATE ev_arrears SET outstanding = outstanding - ?, "
            "total_recovered = total_recovered + ?, last_updated=? WHERE person_id=?",
            (take, take, today, person_id),
        )
        cur = conn.execute(
            "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
            "event_type, amount, balance_after, remarks, created_by) "
            "VALUES (?,?,?,?,?,'DEPOSIT_APPLIED',?,?,?,?)",
            (
                person_id,
                "",
                "",
                today,
                today,
                take,
                _gen_balance(conn, person_id),
                f"Security deposit applied to EV rent dues{tag}",
                created_by,
            ),
        )
        attribute_recovery(conn, person_id=person_id, recovery_event_id=cur.lastrowid, amount=take)
        remaining -= take
        applied += take

    # 2) General dues (negative balance).
    if remaining > 0:
        brow = conn.execute(
            "SELECT current_balance FROM balances WHERE person_id=?", (person_id,)
        ).fetchone()
        bal = int(brow["current_balance"]) if brow else 0
        take2 = min(remaining, max(0, -bal))
        if take2 > 0:
            new_bal = bal + take2
            conn.execute(
                "UPDATE balances SET current_balance=?, last_updated=? WHERE person_id=?",
                (new_bal, today, person_id),
            )
            conn.execute(
                "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
                "event_type, amount, balance_after, remarks, created_by) "
                "VALUES (?,?,?,?,?,'DEPOSIT_APPLIED',?,?,?,?)",
                (
                    person_id,
                    "",
                    "",
                    today,
                    today,
                    take2,
                    new_bal,
                    f"Security deposit applied to carried dues{tag}",
                    created_by,
                ),
            )
            applied += take2
    return applied
