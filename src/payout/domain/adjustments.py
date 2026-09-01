"""Manual ledger adjustments and EV maintenance logging.

post_adjustment moves a person's running balance and records an immutable
ADJUSTMENT transaction. log_maintenance records an EV downtime window that the
rent engine then excludes automatically.
"""

from __future__ import annotations

import sqlite3
from datetime import date


def post_adjustment(
    conn: sqlite3.Connection,
    person_id: int,
    amount: float,
    reason: str,
    created_by: str,
    *,
    rider_id: str = "",
    company: str = "",
) -> float:
    """Credit (amount > 0) or debit (amount < 0) a balance. Returns new balance."""
    if not reason:
        raise ValueError("An adjustment requires a reason.")
    row = conn.execute(
        "SELECT current_balance FROM balances WHERE person_id=?", (person_id,)
    ).fetchone()
    current = row["current_balance"] if row else 0
    new_balance = current + amount
    today = date.today().isoformat()
    # Upsert: a rider onboarded from a payout preview has no balances row yet,
    # and a plain UPDATE affected zero rows while the ADJUSTMENT transaction
    # below was still written — the money vanished but the audit said it moved.
    conn.execute(
        "INSERT INTO balances (person_id, current_balance, last_updated) VALUES (?,?,?) "
        "ON CONFLICT(person_id) DO UPDATE SET current_balance=excluded.current_balance, "
        "last_updated=excluded.last_updated",
        (person_id, new_balance, today),
    )
    conn.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, "
        "cycle_end, event_type, amount, balance_after, remarks, created_by) "
        "VALUES (?,?,?,?,?,'ADJUSTMENT',?,?,?,?)",
        (person_id, rider_id, company, today, today, amount, new_balance, reason, created_by),
    )
    return new_balance


def log_maintenance(
    conn: sqlite3.Connection, ev_id: str, from_date: date, to_date: date,
    reason: str, created_by: str,
) -> None:
    """Record an EV maintenance window; rent skips chargeable days inside it."""
    fd = from_date.isoformat() if hasattr(from_date, "isoformat") else str(from_date)
    td = to_date.isoformat() if hasattr(to_date, "isoformat") else str(to_date)
    conn.execute(
        "INSERT INTO ev_maintenance (ev_id, from_date, to_date, reason, created_by) "
        "VALUES (?,?,?,?,?)",
        (ev_id, fd, td, reason, created_by),
    )
