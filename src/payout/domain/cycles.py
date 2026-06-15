"""Next-cycle date computation per company.

Each active company has a fixed cadence. Most are simple weekly (Mon-Sun or
Sun-Sat); Spencer's runs four fixed slots per month: 1-7, 8-14, 15-21, 22-end.

The helpers are pure functions of the last-committed cycle_end so they're
trivially testable.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta
from typing import Optional

# Companies with a vanilla 7-day cycle: next_start = last_end + 1 day,
# next_end = next_start + 6 days. Membership covers what's currently active.
WEEKLY_COMPANIES = {"Dealshare", "Myntra", "Blitz"}


def next_weekly_cycle(last_end: date) -> tuple[date, date]:
    start = last_end + timedelta(days=1)
    return start, start + timedelta(days=6)


def next_spencers_cycle(last_end: date) -> tuple[date, date]:
    """Spencer's fixed slots: 1-7, 8-14, 15-21, 22-end-of-month."""
    y, m, d = last_end.year, last_end.month, last_end.day
    last_day = monthrange(y, m)[1]
    if d == 7:
        return date(y, m, 8), date(y, m, 14)
    if d == 14:
        return date(y, m, 15), date(y, m, 21)
    if d == 21:
        return date(y, m, 22), date(y, m, last_day)
    if d == last_day:
        if m == 12:
            return date(y + 1, 1, 1), date(y + 1, 1, 7)
        return date(y, m + 1, 1), date(y, m + 1, 7)
    # Fallback for an unexpected end-date — keep the same slot length forward
    span = max(7, (last_end - last_end.replace(day=max(1, d - 6))).days + 1)
    start = last_end + timedelta(days=1)
    return start, start + timedelta(days=span - 1)


def next_cycle_for(company: str, last_end: Optional[date]) -> tuple[date, date]:
    """Return (next_start, next_end). If no history, anchor on most recent
    Monday for weekly companies, or the current slot for Spencer's."""
    if last_end is None:
        today = date.today()
        if company == "Spencer's":
            # Find the slot today falls in and return the NEXT one.
            d = today.day
            last_day = monthrange(today.year, today.month)[1]
            if d <= 7:
                anchor = date(today.year, today.month, 7)
            elif d <= 14:
                anchor = date(today.year, today.month, 14)
            elif d <= 21:
                anchor = date(today.year, today.month, 21)
            else:
                anchor = date(today.year, today.month, last_day)
            return next_spencers_cycle(anchor)
        # Weekly: anchor on last Sunday (so next cycle is Mon-Sun)
        days_back = (today.weekday() + 1) % 7  # 0 if today is Sunday
        last_sunday = today - timedelta(days=days_back if days_back else 7)
        return next_weekly_cycle(last_sunday)

    if company == "Spencer's":
        return next_spencers_cycle(last_end)
    return next_weekly_cycle(last_end)
