"""Who pays a rider, and therefore how his EV rent reaches the books.

A company has a ``payment_model`` — ``payout_file`` (they send a file, we pay
the riders), ``per_order`` and ``salary`` (we compute the pay, we pay),
``direct`` (they pay the riders themselves; we never hold their money). From
September 2026 one client, Zomato, runs two programmes at once, one direct
and one through us, so the model also lives on the rider id:
``rider_master.payment_model`` overrides the company's when set.

The question the engine actually asks is about a *person*: is there any
active id through which we will ever pay him? If there is, his rent is
deducted by that company's cycle like everybody else's. If there is not, no
cycle will ever run for him, and his rent has to be booked as RENT_DUE and
collected in cash. That is ``person_is_direct_pay``.
"""

from __future__ import annotations

CYCLE_MODELS = ("payout_file", "per_order", "salary")
VALID_MODELS = ("payout_file", "per_order", "salary", "direct")


def rider_payment_model(row) -> str:
    """Effective model for one rider_master row joined to its company:
    the id's own override, else the company's, else ``direct``."""
    own = (row["payment_model"] if "payment_model" in row.keys() else None) or None  # noqa: SIM118 — sqlite3.Row has keys() but no __contains__
    if own:
        return own
    company = (row["company_model"] if "company_model" in row.keys() else None) or None  # noqa: SIM118 — sqlite3.Row has keys() but no __contains__
    return company or "direct"


def person_pay_models(conn, person_id: int) -> list[dict]:
    """Every active rider id of the person with its effective model."""
    rows = conn.execute(
        "SELECT rm.rider_id, rm.company, rm.payment_model, "
        "       c.payment_model AS company_model, COALESCE(c.is_active, 1) AS company_active "
        "FROM rider_master rm LEFT JOIN companies c ON c.company_name = rm.company "
        "WHERE rm.person_id=? AND COALESCE(rm.is_active, 1) = 1",
        (person_id,),
    ).fetchall()
    return [
        {"rider_id": r["rider_id"], "company": r["company"], "model": rider_payment_model(r)}
        for r in rows
        if int(r["company_active"] or 1) == 1
    ]


def person_is_direct_pay(conn, person_id: int) -> bool:
    """True when no active id of his will ever be paid through us."""
    models = person_pay_models(conn, person_id)
    return bool(models) and all(m["model"] not in CYCLE_MODELS for m in models)
