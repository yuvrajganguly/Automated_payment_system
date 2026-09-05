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
    if days == cycle_days:
        return int(weekly_paise)  # exact full-cycle
    q = (Decimal(int(weekly_paise)) * days / cycle_days).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    return int(q)  # partial OR catch-up (>cycle_days)


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


# ── API boundary: paise (internal) -> rupees (JSON) ─────────────────────────
# Money keys that appear in API/JSON responses. Counts, days, percentages and
# ids are deliberately excluded. A missed key shows as a 100x value (loud); a
# wrong inclusion shows as /100 (also loud) — both caught by the value-for-value
# regression check.
MONEY_KEYS = frozenset(
    {
        "amount",
        "applied_amount",
        "balance",
        "balance_after",
        "current_balance",
        "pending_xc_rent",
        "weekly_rate",
        "per_order_rate",
        "daily_rate",
        "daily_cost",
        "provider_cost",
        "outstanding",
        "arrears_outstanding",
        "total_missed",
        "total_recovered",
        "cod_missed",
        "cod_recovered",
        "cod_outstanding",
        "dues_outstanding",
        "ev_arrears",
        "dues",
        "dues_dormant",
        "silent",
        "total_dues",
        "expected",
        "collected",
        "missed",
        "recovered",
        "pending",
        "rider_expected",
        "rider_collected",
        "rider_missed",
        "rider_recovered",
        "rider_pending",
        "provider_owed",
        "shortfall",
        "rent_expected",
        "rent_collected",
        "rent_missed",
        "rent_pending",
        "arrears_recovered",
        "refunded",
        "arrears_written_off",
        "written_off",
        "deposit_applied",
        "prior_dues_collected",
        "dues_added",
        "carried_forward",
        "credit_offset",
        "cod_held",
        "cod_uncleared",
        "charged",
        "credit",
        "ev_arrears_active",
        "ev_arrears_dormant",
        "offset_applied",
        "manual_rent",
        "cod",
        "hold",
        "payout",
        "total_arrears",
        "arrears_total",
        "total_payout",
        "total_release",
        "total_rent_charged",
        "total_rent_collected",
        "total_rent_missed",
        "bill_total",
        "their_amount",
        "our_amount",
        "discrepancy",
        "gross",
        "gross_payout",
        "rent",
        "release",
        "released",
        "net_release",
        "net_pay",
        "opening_dues",
        "opening_ev_arrears",
        "rent_charged",
        "rent_collected_this_cycle",
        "rent_missed_this_cycle",
        "applied_to_arrears",
        "applied_to_rent",
        "new_balance",
        "value",
        # EV Rent page (per-rider + cycle totals): paise sums of t.amount
        "expected_rent",
        "collected_rent",
        "prior_recovered",
        "rolled_forward",
        "arrears_rent",
        "arrears_net",
        "arrears_recovered_later",
        "future_arrears_recovered",
        "future_xc_recovered",
        # Dashboard inactive-EVs list (ledger daily_cost sum)
        "missed_amount",
        # COD page + Payments reconciliation
        "total_pending",
        "recent_payout",
        "expected_amount",
        # Dashboard: partial rent collection (charged minus collected, this window)
        "rent_partial",
        # Dashboard breakdown drawers: "Owed to providers" (SUM provider_cost) and
        # "COD held" (SUM cod amount) columns — were missing, rendered 100x.
        "owed",
        "held",
        # Analytics endpoints (routes/analytics.py): weekly series + fleet P&L
        "dues_delta",
        "earned",
        "margin",
        # Ledger-credit auto-settlement against EV arrears (routes report it)
        "arrears_settled_from_credit",
        # EV Rent page cycle rows (ev_rent.py): paise sums that the page adds to
        # rupee totals — were missing.
        "collected_current",
        "rolled_recovered_later",
        "rolled_forward_net",
    }
)


def rupeeize(obj):
    """Recursively convert MONEY_KEYS values in a JSON-able structure from
    integer paise to rupee floats, for the API boundary."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in MONEY_KEYS and isinstance(v, (int, float)) and not isinstance(v, bool):
                out[k] = to_rupees(v)
            else:
                out[k] = rupeeize(v)
        return out
    if isinstance(obj, list):
        return [rupeeize(x) for x in obj]
    return obj
