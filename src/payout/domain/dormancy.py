"""One definition of DORMANT ("silent") for every view that lists debt.

A person is dormant when they hold NO open EV assignment but still owe
money — EV back-rent, or general carry-forward dues if they ever held an
EV (a rider who never had an EV keeps their dues on the active path:
those clear automatically from the next payout).

Views must not each re-derive this; they call :func:`dormant_person_sql`
so the rule can never drift between the Arrears page, the dashboard
drawers, the analytics tabs, and the exports. The engine mirrors the
same rule when deciding to HOLD a payout (see engine.dormant_hold).
"""

from __future__ import annotations


def dormant_person_sql(person_col: str) -> str:
    """SQL boolean expression: is the person identified by ``person_col``
    dormant? Self-contained (correlated subqueries only), so it works in
    any query that has a person-id column in scope — no extra joins
    required. Valid on both SQLite and PostgreSQL.
    """
    p = person_col
    return (
        f"(NOT EXISTS (SELECT 1 FROM ev_assignments _oa "
        f"WHERE _oa.person_id = {p} AND _oa.returned_date IS NULL) "
        f"AND (COALESCE((SELECT _ea.outstanding FROM ev_arrears _ea "
        f"WHERE _ea.person_id = {p}), 0) > 0 "
        f"OR (COALESCE((SELECT _b.current_balance FROM balances _b "
        f"WHERE _b.person_id = {p}), 0) < 0 "
        f"AND EXISTS (SELECT 1 FROM ev_assignments _ra "
        f"WHERE _ra.person_id = {p} AND _ra.returned_date IS NOT NULL))))"
    )
