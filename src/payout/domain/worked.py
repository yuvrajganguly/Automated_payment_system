"""Has this rider worked recently?

Distinct from ``dormancy.py``, which asks a *money* question (no EV, but still
owing) and from the ``/inactive`` route, which lists EV holders whose rent has
been missed. This module answers the plain operational one the recruiter app
asks: **is this rider still working?**

The rule, as the office states it (2026-09-11):

    Take every rider id this person holds that is still switched on. If none of
    them appeared in its own company's most recent payout, the person is not
    working. Ids the recruiter has switched off are not expected to appear, and
    an id created after that company's last cycle began could not have
    appeared, so neither counts against them.

Four things are load-bearing in that sentence.

* **Each company's own last cycle**, not a rolling window. The rule this
  replaced was "a paysheet company paid them for a cycle ending in the last 12
  days", and its own docstring admitted the flaw: a company whose cycle had
  not been run for a fortnight made *all* of its riders read as inactive. The
  office would ask why half the roster had gone idle and the answer was "we
  have not run Kaptan yet". Keyed to the company's last committed cycle
  instead, a rider who was in that payout stays active however long ago the
  office ran it, and the number stops moving on its own.

* **Any one id is enough.** A person working Kaptan and idle at Jiffy is
  working. The question is about a human, not a row.

* **The roster switch is an input, not an override.** ``is_active = 0`` on an
  id means "do not expect this one in a payout" — the recruiter has said the
  rider left that company. It does not by itself make the person inactive:
  somebody with a switched-off Jiffy id and a live Kaptan id is working. Only
  when *every* remaining id fails does the person read as not working.

* **A new id is exempt, and exempts itself.** Onboarded after the company's
  last cycle started, they could not possibly have been in that payout, so its
  absence is not evidence. Once the next cycle runs, the same id is judged
  like any other — the exemption expires on its own rather than on a
  fixed number of days that would be wrong for every company whose cycle is
  longer or has slipped.

Only companies that send us a paysheet can answer the question at all
(``payment_model = 'payout_file'``). A ``direct`` company pays its riders
itself, a ``per_order`` company is counted off a dashboard by hand, and a
``salary`` company is marked present by the office; an id at one of those is
excluded from the test exactly like a switched-off one. A person who holds
*only* such ids has no evidence either way, and reads as working rather than
being accused of idleness by a company that never reports.

A company the office has **switched off** (``is_active = 0``) is excluded the
same way. It will never run another cycle, so its last one stays the last one
for ever and every id there would read absent from it permanently — a company
we stopped running would slowly turn its whole roster idle and the number
would be measuring our own decision rather than the rider's work.

The consequence worth knowing before quoting a number from this: it answers
"were they in the last payout we ran", not "did they ride yesterday". That is
the honest limit of what the ledger knows.
"""

from __future__ import annotations

# Kept for the API's `active_within_days` field and the app's wording. It no
# longer gates anything: the rule is the last cycle, not a window.
ACTIVE_WITHIN_DAYS = 12

# Ledger rows that mean "this rider earned in this cycle". A rent or arrears
# row alone does not: rent accrues against a rider who has stopped working.
EARNING_EVENTS = ("PAYOUT",)

# A company whose payout file is the evidence. See the module docstring.
_PAYSHEET = "COALESCE(_c.payment_model, 'payout_file') = 'payout_file'"

# A company the office has switched off will never run another cycle, so its
# last one stays "the last one" for ever and every id there reads absent from
# it permanently. Nobody expects work from a company we have stopped running,
# so its ids drop out of the test entirely — the same treatment a switched-off
# rider id gets. NULL means the companies row is gone rather than switched off,
# and a deleted company must not flip its riders (see the LEFT JOIN note).
_LIVE_COMPANY = "COALESCE(_c.is_active, 1) = 1"

# That company's most recent committed run. company_cycles has one row per
# (company, cycle) and is written only on commit, so MAX(cycle_end) is "the
# last payout we actually ran" — an ad-hoc surge run deliberately does not
# appear here, which is what keeps a surge payment from counting as a cycle.
_LAST_CYCLE_END = (
    "(SELECT MAX(_cc.cycle_end) FROM company_cycles _cc WHERE _cc.company = _rm.company)"
)
_LAST_CYCLE_START = (
    "(SELECT MAX(_cc.cycle_start) FROM company_cycles _cc "
    " WHERE _cc.company = _rm.company AND _cc.cycle_end = "
    f"   {_LAST_CYCLE_END})"
)


def _expectant(person_col: str, extra: str = "") -> str:
    """Rider ids of this person that we *expect* in a payout, as an EXISTS.

    An id is expectant when the recruiter has left it switched on, its company
    sends us a paysheet, that company has actually run a cycle, and the id
    existed when that cycle began. Anything else is excluded from the test
    rather than counted against the rider — see the module docstring.

    ``extra`` is ANDed on, and is how the caller asks for "…and it appeared".
    """
    return (
        "EXISTS (SELECT 1 FROM rider_master _rm "
        # LEFT JOIN, not INNER: the ledger and the roster outlive the companies
        # row. Deleting a company must not flip every rider it ever paid from
        # working to idle — the number would just quietly become wrong, which
        # is the worst failure this rule can have.
        "LEFT JOIN companies _c ON _c.company_name = _rm.company "
        f"WHERE _rm.person_id = {person_col} "
        # Switched off by a recruiter: not expected, so not evidence.
        "AND _rm.is_active = 1 "
        # A company that cannot report cannot accuse.
        f"AND {_PAYSHEET} "
        # Switched off by the office: no further cycles, so no expectation.
        f"AND {_LIVE_COMPANY} "
        # Never run: nothing to be absent from.
        f"AND {_LAST_CYCLE_END} IS NOT NULL "
        # Created after the cycle began — could not have been in it. On the
        # start day itself they could have worked, so that still counts.
        f"AND COALESCE(substr(_rm.created_at, 1, 10), '9999-12-31') <= {_LAST_CYCLE_START} "
        f"{extra})"
    )


def worked_person_sql(person_col: str) -> str:
    """SQL boolean: is this person working?

    False only when we expected them somewhere and they were nowhere: at least
    one expectant id, and none of them in its company's last payout. True when
    any expectant id appeared, and true when there are no expectant ids at all
    — a person whose only ids are switched off, brand new, or at companies
    that never report has no evidence against them, and "we cannot tell" must
    not read as "not working".

    ``person_col`` is the outer query's person id expression, e.g.
    ``rm.person_id``. Qualify it — an unqualified ``person_id`` binds to the
    subquery's own ``rider_master`` and the predicate becomes always-true.

    Written in SQLite dialect and translated for PostgreSQL at execution time,
    like the rest of the codebase's SQL.
    """
    events = ", ".join(f"'{e}'" for e in EARNING_EVENTS)
    appeared = (
        "AND EXISTS (SELECT 1 FROM transactions _t "
        "            WHERE _t.person_id = _rm.person_id "
        "              AND _t.company = _rm.company "
        f"             AND _t.event_type IN ({events}) "
        f"             AND _t.cycle_end = {_LAST_CYCLE_END}) "
    )
    return f"((NOT {_expectant(person_col)}) OR {_expectant(person_col, appeared)})"


def active_person_sql(person_col: str, days: int = ACTIVE_WITHIN_DAYS) -> str:
    """SQL boolean: is this rider still working?

    ``days`` is accepted and ignored — the rule is no longer a window. The
    parameter stays so the dozen call sites that passed it keep working and so
    a future change of mind has somewhere to land.
    """
    return worked_person_sql(person_col)


def last_worked_sql(person_col: str) -> str:
    """SQL scalar subquery: the end date of the most recent cycle a paysheet
    company paid this person for, or NULL if there has never been one.

    This is a *display* value — "last paid for a cycle ending …" — and is
    deliberately not the rule above. A rider can be working (they were in the
    last cycle Kaptan ran) while this date looks old (Kaptan was run three
    weeks ago), and showing the date next to the flag is how an operator sees
    that for themselves instead of doubting the flag.
    """
    events = ", ".join(f"'{e}'" for e in EARNING_EVENTS)
    return (
        "(SELECT MAX(_wt.cycle_end) FROM transactions _wt "
        "LEFT JOIN companies _wc ON _wc.company_name = _wt.company "
        f"WHERE _wt.person_id = {person_col} "
        f"AND _wt.event_type IN ({events}) "
        "AND COALESCE(_wc.payment_model, 'payout_file') = 'payout_file')"
    )


__all__ = [
    "ACTIVE_WITHIN_DAYS",
    "EARNING_EVENTS",
    "active_person_sql",
    "last_worked_sql",
    "worked_person_sql",
]
