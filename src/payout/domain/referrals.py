"""Rider referrals.

A rider (the *referrer*) brings a new rider in; the recruiter records it
when onboarding. Once the new rider has **worked four weeks** — 28 days
since onboarding, still holding an active rider id, and at least one payout
received — the referrer earns **₹1,000 in two ₹500 instalments**: the first
in the referrer's payout processed after the month is reached, the second in
the payout after that. The engine pays them as ADJUSTMENT credits right
before settlement, so they ride out with that cycle's release. Dry runs show
them and roll back like everything else.
"""

from __future__ import annotations

from datetime import date, timedelta

from payout.domain.adjustments import post_adjustment

QUALIFY_DAYS = 28
BONUS_PAISE = 100_000  # ₹1,000
INSTALLMENTS = 2
INSTALLMENT_PAISE = BONUS_PAISE // INSTALLMENTS


class ReferralError(ValueError):
    """The referral cannot be recorded; the message says why."""


def create_referral(
    conn, *, new_person_id: int, referrer_person_id: int, company: str | None, created_by: str
) -> dict:
    if new_person_id == referrer_person_id:
        raise ReferralError("A rider cannot refer themselves")
    for pid, what in ((new_person_id, "new rider"), (referrer_person_id, "referrer")):
        if not conn.execute("SELECT 1 FROM person_registry WHERE person_id=?", (pid,)).fetchone():
            raise ReferralError(f"Unknown {what} (person {pid})")
    if conn.execute("SELECT 1 FROM referrals WHERE new_person_id=?", (new_person_id,)).fetchone():
        raise ReferralError("This rider already has a referrer on file")
    cur = conn.execute(
        "INSERT INTO referrals (new_person_id, referrer_person_id, company, created_by) "
        "VALUES (?,?,?,?)",
        (new_person_id, referrer_person_id, company, created_by),
    )
    return get_referral(conn, cur.lastrowid)


def get_referral(conn, referral_id: int) -> dict:
    return dict(conn.execute(_SELECT + " WHERE r.id=?", (referral_id,)).fetchone())


_SELECT = (
    "SELECT r.id, r.new_person_id, np.display_name AS new_name, "
    "       r.referrer_person_id, rp.display_name AS referrer_name, r.company, "
    "       r.created_by, r.created_at, r.qualified_on, r.installments_paid, "
    "       r.last_paid_cycle_end, r.status, r.note "
    "FROM referrals r "
    "JOIN person_registry np ON np.person_id = r.new_person_id "
    "JOIN person_registry rp ON rp.person_id = r.referrer_person_id"
)


def list_referrals(
    conn, *, person_id: int | None = None, status: str | None = None, created_by: str | None = None
) -> list[dict]:
    where, params = [], []
    if person_id is not None:
        where.append("(r.new_person_id=? OR r.referrer_person_id=?)")
        params += [person_id, person_id]
    if status:
        where.append("r.status=?")
        params.append(status)
    if created_by:
        where.append("r.created_by=?")
        params.append(created_by)
    sql = _SELECT + ((" WHERE " + " AND ".join(where)) if where else "") + " ORDER BY r.id DESC"
    return [dict(x) for x in conn.execute(sql, params).fetchall()]


def _onboarded_on(conn, person_id: int) -> date | None:
    """When the new rider joined: their earliest rider row."""
    row = conn.execute(
        "SELECT MIN(created_at) AS c FROM rider_master WHERE person_id=?", (person_id,)
    ).fetchone()
    if not row or not row["c"]:
        return None
    try:
        return date.fromisoformat(str(row["c"])[:10])
    except ValueError:
        return None


def qualification_date(conn, referral: dict, as_of: date) -> date | None:
    """The date the new rider completed four weeks, if that is on or before
    ``as_of`` and they are still working; None otherwise."""
    if referral.get("qualified_on"):
        return date.fromisoformat(referral["qualified_on"])
    start = _onboarded_on(conn, referral["new_person_id"])
    if start is None:
        return None
    due = start + timedelta(days=QUALIFY_DAYS)
    if due > as_of:
        return None
    active = conn.execute(
        "SELECT 1 FROM rider_master WHERE person_id=? AND is_active=1",
        (referral["new_person_id"],),
    ).fetchone()
    if not active:
        return None
    paid = conn.execute(
        "SELECT 1 FROM transactions WHERE person_id=? AND event_type='PAYOUT' AND amount>0 LIMIT 1",
        (referral["new_person_id"],),
    ).fetchone()
    if not paid:
        return None
    return due


def pay_installments(
    conn, *, referrer_person_id: int, company: str, cycle_start, cycle_end, created_by: str
) -> list[dict]:
    """Called by the engine for a rider being paid at ``company`` this cycle.
    Credits every instalment that is due — one per referral per cycle — and
    returns what was paid: [{referral_id, new_name, installment, amount}]."""
    end = cycle_end if isinstance(cycle_end, date) else date.fromisoformat(str(cycle_end)[:10])
    end_iso = end.isoformat()
    paid: list[dict] = []
    for ref in list_referrals(conn, person_id=referrer_person_id):
        if ref["referrer_person_id"] != referrer_person_id:
            continue
        if ref["status"] in ("paid", "void") or ref["installments_paid"] >= INSTALLMENTS:
            continue
        if ref["last_paid_cycle_end"] and ref["last_paid_cycle_end"] >= end_iso:
            continue  # one instalment per cycle; never twice for the same cycle
        q = qualification_date(conn, ref, end)
        if q is None:
            continue
        n = ref["installments_paid"] + 1
        post_adjustment(
            conn,
            referrer_person_id,
            INSTALLMENT_PAISE,
            f"Referral bonus {n}/{INSTALLMENTS} — {ref['new_name']} completed four weeks",
            created_by,
            company=company,
        )
        conn.execute(
            "UPDATE referrals SET installments_paid=?, last_paid_cycle_end=?, qualified_on=?, "
            "status=? WHERE id=?",
            (
                n,
                end_iso,
                q.isoformat(),
                "paid" if n >= INSTALLMENTS else "paying",
                ref["id"],
            ),
        )
        paid.append(
            {
                "referral_id": ref["id"],
                "new_person_id": ref["new_person_id"],
                "new_name": ref["new_name"],
                "installment": n,
                "amount": INSTALLMENT_PAISE,
            }
        )
    return paid
