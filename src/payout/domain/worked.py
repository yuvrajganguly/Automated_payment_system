"""Has this rider worked recently?

Distinct from ``dormancy.py``, which asks a *money* question (no EV, but still
owing) and from the ``/inactive`` route, which lists EV holders whose rent has
been missed. This module answers the plain operational one the recruiter app
asks: **is this rider still working?**

The rule, as the office states it: a rider is active if a company that sends us
a paysheet paid them for a cycle that ended within the last 12 days.

Two deliberate narrowings sit in that sentence:

* **"a company that sends us a paysheet"** is ``payment_model='payout_file'``.
  The others cannot answer the question — a ``direct`` company pays its riders
  itself and we never see whether they worked, a ``per_order`` company is
  counted off their dashboard by hand, and a ``salary`` company is marked
  present by the office. Counting those would make a rider look inactive for a
  reason that has nothing to do with them.
* **the cycle's end date, not the payment date.** Cycles are billed weekly in
  arrears, so ``cycle_end`` is the last day the rider could have worked in that
  cycle. Using ``created_at`` would make every rider look active on the day the
  office happened to run the payout.

The consequence worth knowing before quoting a number from this: a company
whose cycle has not been run for a fortnight makes all of its riders read as
inactive, because there is no evidence either way. That is the honest answer —
we know when we last paid someone, not when they last rode.
"""

from __future__ import annotations

# Days since the end of the last paid cycle, past which a rider reads inactive.
ACTIVE_WITHIN_DAYS = 12

# Ledger rows that mean "this rider earned in this cycle". A rent or arrears
# row alone does not: rent accrues against a rider who has stopped working.
EARNING_EVENTS = ("PAYOUT",)


def last_worked_sql(person_col: str) -> str:
    """SQL scalar subquery: the end date of the most recent cycle a paysheet
    company paid this person for, or NULL if there has never been one.

    ``person_col`` is the outer query's person id expression, e.g. ``p.person_id``.
    Written in SQLite dialect and translated for PostgreSQL at execution time,
    like the rest of the codebase's SQL.
    """
    events = ", ".join(f"'{e}'" for e in EARNING_EVENTS)
    return (
        "(SELECT MAX(_wt.cycle_end) FROM transactions _wt "
        # LEFT JOIN, not INNER: the ledger outlives the companies row. Deleting
        # a company leaves its transactions in place, and an inner join would
        # silently flip every rider it ever paid from working to idle — the
        # number would just quietly become wrong, which is the worst failure
        # this table can have. A payout row whose company row is gone is still
        # evidence that somebody worked.
        "LEFT JOIN companies _wc ON _wc.company_name = _wt.company "
        f"WHERE _wt.person_id = {person_col} "
        f"AND _wt.event_type IN ({events}) "
        "AND COALESCE(_wc.payment_model, 'payout_file') = 'payout_file')"
    )


def active_person_sql(person_col: str, days: int = ACTIVE_WITHIN_DAYS) -> str:
    """SQL boolean: this person worked within ``days``.

    A rider a paysheet company has never paid is not active — there is no
    evidence they are working, which is exactly what the office wants to see.
    """
    return (
        f"({last_worked_sql(person_col)} IS NOT NULL "
        f"AND {last_worked_sql(person_col)} >= date('now', '-{int(days)} day'))"
    )


__all__ = ["ACTIVE_WITHIN_DAYS", "EARNING_EVENTS", "active_person_sql", "last_worked_sql"]
