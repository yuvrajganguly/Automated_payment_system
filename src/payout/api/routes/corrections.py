"""Corrections feed — every manual change to the books, in one place.

The engine writes with ``created_by='engine'`` and migrations with
``created_by='migration:*'``; everything else on the transactions trail was a
human (or a human-triggered heal): adjustments, manual rent payments, arrears
reversals from backdated returns, COD clearances, opening balances. This feed
is that slice, newest first, so "what did we patch by hand, and when?" has an
answer that isn't scrolling the raw audit log.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from payout.api.auth import get_current_user
from payout.db import get_connection

router = APIRouter()

_PAGE_MAX = 500


@router.get("")
def corrections_feed(
    limit: int = 100,
    person_id: int | None = None,
    event_type: str | None = None,
    _: dict = Depends(get_current_user),
) -> list[dict]:
    """Manual transactions, newest first.

    Cycle output (PAYOUT/RENT/RENT_MISSED/...) is excluded even though it
    carries the committing operator's email — a committed cycle isn't a
    correction. What IS one: balance adjustments, arrears reversals from
    backdated returns, opening balances, and manual rent payments (their
    RENT_RECOVERED / RENT_COLLECTED rows are tagged "manual rent" in remarks).
    Migration sweeps are excluded.
    """
    limit = max(1, min(int(limit), _PAGE_MAX))
    q = (
        "SELECT t.id, t.person_id, pr.display_name, t.rider_id, t.company, "
        "       t.cycle_start, t.cycle_end, t.event_type, t.amount, t.balance_after, "
        "       t.days, t.remarks, t.created_at, t.created_by "
        "FROM transactions t "
        "JOIN person_registry pr ON pr.person_id = t.person_id "
        "WHERE (t.event_type IN ('ADJUSTMENT', 'RENT_REVERSAL', 'OPENING') "
        "       OR t.remarks LIKE 'manual rent%') "
        "  AND COALESCE(t.created_by, '') NOT LIKE 'migration:%' "
    )
    params: list = []
    if person_id is not None:
        q += "AND t.person_id = ? "
        params.append(person_id)
    if event_type:
        q += "AND t.event_type = ? "
        params.append(event_type)
    q += "ORDER BY t.id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(q, params).fetchall()
    return [dict(r) for r in rows]
