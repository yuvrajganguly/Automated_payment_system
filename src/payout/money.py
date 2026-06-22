"""Money is integer **paise** everywhere internal (DB + domain).

Float rupees are only used at the API boundary for human-readable JSON; the
storage and every calculation are exact integers, so cents never drift no
matter how many transactions are summed.

Rounding policy: half-up to the nearest paise. Proration of a weekly rate is
rounded **once** on the total (``prorate``), and a cycle's per-day ledger costs
are split so they sum back to the exact cycle rent (``split_evenly``) — the
day-grain ledger therefore reconciles to the paisa against the RENT row.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal


def to_paise(rupees) -> int:
    """Rupees (float/str/Decimal/int) -> integer paise, half-up."""
    if rupees is None:
        return 0
    return int((Decimal(str(rupees)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_rupees(paise) -> float:
    """Integer paise -> rupees float, for API/display only."""
    if paise is None:
        return 0.0
    return round(int(paise) / 100.0, 2)


def prorate(weekly_paise: int, days: int, cycle_days: int = 7) -> int:
    """Rent for ``days`` of a weekly rate, in paise.

    A full standard cycle bills the weekly rate exactly; a partial cycle is the
    weekly rate scaled by days/cycle_days, rounded half-up **once** on the total
    (not per day) so there is no per-day drift.
    """
    if days <= 0:
        return 0
    if days >= cycle_days:
        return int(weekly_paise)
    q = (Decimal(int(weekly_paise)) * days / cycle_days).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP)
    return int(q)


def split_evenly(total_paise: int, n: int) -> list[int]:
    """Split ``total_paise`` into ``n`` per-day amounts that sum to the total.

    base each, with the remainder spread one paise at a time over the first
    days — so summing the day-ledger always equals the exact cycle rent.
    """
    if n <= 0:
        return []
    total = int(total_paise)
    base, rem = divmod(total, n)
    return [base + (1 if i < rem else 0) for i in range(n)]
