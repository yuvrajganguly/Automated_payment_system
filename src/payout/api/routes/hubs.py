"""Stores (hubs) per company: zone and store-level pay.

Hubs are free text on rider rows (they arrive with company files and with
onboarding). ``company_hubs`` is where an admin says which zone — North,
South or Misc — a store is in, and for companies we pay ourselves what the
store pays when it differs from the company default (per-order rate,
salary, incentives). A hub with no zone yet is "unassigned"; its riders take
the zone of the recruiter who onboarded them until it is classified.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from payout.api.auth import get_current_user, require_admin
from payout.db import get_connection
from payout.domain.activity import diff_fields, record_activity
from payout.domain.placeholders import PLACEHOLDER_PREFIX
from payout.money import to_paise

router = APIRouter()

ZONES = ("North", "South", "Misc")


def normalize_zone(zone: str | None) -> str | None:
    """ "north" → "North"; blank → None; anything else → 400."""
    z = (zone or "").strip().title()
    if not z:
        return None
    if z not in ZONES:
        raise HTTPException(400, f"zone must be one of {', '.join(ZONES)} (or empty to clear)")
    return z


def zone_filter(zone: str | None) -> str | None:
    """Normalise a ``?zone=`` query value: ``North`` / ``South`` / ``Misc`` /
    ``unassigned`` (any case) or None; anything else is a 400."""
    z = (zone or "").strip().lower()
    if not z or z == "all":
        return None
    if z == "unassigned":
        return z
    if z.title() in ZONES:
        return z
    raise HTTPException(400, f"zone must be one of {', '.join(ZONES)}, unassigned or all")


def fenced_zone(user: dict) -> str | None:
    """The one zone this caller may look at, lowercased, or None for no fence.

    Field staff are fenced to the zone on their account: a North recruiter has
    no business in South's stores, and until now the only thing between them
    and South was a filter chip they could simply not press. Hiding the chip
    without this would be theatre — ``GET /riders?zone=South`` still answered.

    Two deliberate exemptions. **Admins and the creator** are never fenced;
    they run the whole board. **A recruiter with no zone set** is not fenced
    either — an account nobody has placed yet has to be able to see the work,
    and the alternative is a new joiner staring at an empty app on their first
    morning.
    """
    if user.get("role") in ("admin", "creator"):
        return None
    zone = (user.get("zone") or "").strip()
    return zone.lower() or None


def zone_scope(user: dict, zone: str | None) -> str | None:
    """``zone_filter`` with the caller's fence applied. None = everything.

    A fenced caller gets their own zone and nothing else: not South's stores,
    not the Misc ones, and not the stores nobody has classified yet.

    That last part used to be the opposite. This function returned a second
    flag that pulled unzoned rows into a fenced recruiter's view, on the
    reasoning that a store nobody had placed would otherwise be invisible to
    the entire field at once — every recruiter being fenced somewhere. That
    was true when there was no way to place a store. Since the company tab
    grew a stores panel (2026-09-08) an admin can assign a zone in a couple of
    taps, so the fix for an unclassified store is to classify it, not to show
    it to everybody. Admins still find them with ``zone=unassigned``.

    ``zone=unassigned`` is an admin tool — the way to find the stores that
    still need placing. A fenced caller asking for it is refused like any
    other zone that is not theirs; letting it through would hand back the
    exact bucket this fence now excludes, and the fence would be theatre.

    An unfenced caller keeps today's behaviour exactly: what they ask for is
    what they get, and "all" means all.
    """
    fence = fenced_zone(user)
    asked = zone_filter(zone)
    if fence is None:
        return asked
    if asked is None or asked == fence:
        return fence
    raise HTTPException(403, "You can only see your own zone")


# ── riders nobody has placed ────────────────────────────────────────────────
#
# This has now been decided twice, in two different ways, and both decisions
# are worth keeping written down because the second is narrower than the first.
#
# 2026-09-11 morning: tightening the zone fence made every rider with no
# derivable zone invisible to the entire field at once. An "unassigned pool"
# was added — anything with no store and nobody credited rode along with every
# fenced recruiter's zone.
#
# 2026-09-11 afternoon: removed. That pool put the same rider in BOTH zones'
# lists, so two recruiters could each reasonably think he was theirs, and the
# count a North recruiter read off their own screen was not a count of North.
#
# 2026-09-12: brought back, but only for **placeholder ids**. The office's
# reasoning is the part the wide version was missing: a QSPEND id is not a
# rider waiting to be classified, it is a rider whose company has not issued
# an id yet. Somebody has to go and get that id, the job is not zoned, and
# until it is done there is no store to derive a zone from. Showing them to
# both zones is how the job gets picked up at all.
#
# The double-counting objection still stands, so it is bounded: a placeholder
# id is temporary by construction, and the moment the real id replaces it
# (POST /riders/rename-rider-id, which retires the placeholder) the rider
# leaves this pool by themselves. Nothing needs remembering or cleaning up.
#
# Recruit counts are keyed on `recruited_by`, not on zone, so no count moves
# because of this — what widens is which roster and to-do rows a fenced
# recruiter can see.


def sees_placeholder_pool(user: dict) -> bool:
    """Does the placeholder pool ride along with this caller's zone filter?

    Only for a fenced caller. An admin who asks for North wants North; the
    pool is a concession to the fence, not a member of every zone, and an
    admin's ``zone=unassigned`` is the honest way to see this population.
    """
    return fenced_zone(user) is not None


def placeholder_pool_sql(rider_id_expr: str, zone_expr: str) -> str:
    """SQL boolean: this rider is in the placeholder pool.

    A placeholder rider id (``QSPEND…``) and no zone derivable from either the
    store or the recruiter who onboarded them.

    ``substr`` rather than ``LIKE 'QSPEND%'`` on purpose: SQLite's LIKE is
    case-insensitive and PostgreSQL's is not, so the same predicate would
    match different rows on the two backends. Placeholders are generated
    upper-case, so an exact prefix comparison is both correct and identical
    everywhere.
    """
    return f"(substr({rider_id_expr}, 1, 6) = '{PLACEHOLDER_PREFIX}' AND {zone_expr} IS NULL)"


class HubOut(BaseModel):
    company: str
    hub: str
    zone: str | None = None
    per_order_rate: int | None = None  # paise (rupeeized on the way out)
    salary: int | None = None
    incentive_per_order: int | None = None
    incentive_per_day: int | None = None
    notes: str | None = None
    is_active: bool = True
    riders: int = 0  # active rider ids at this store
    evs: int = 0  # EVs currently held by riders of this store
    payment_model: str | None = None  # the company's, so the UI knows which fields apply


class HubIn(BaseModel):
    """Upsert body. Money in rupees; omit a field to leave it alone."""

    zone: str | None = None
    per_order_rate: float | None = None
    salary: float | None = None
    incentive_per_order: float | None = None
    incentive_per_day: float | None = None
    notes: str | None = None
    is_active: bool | None = None


_LIST_SQL = (
    "SELECT h.company, h.hub, ch.zone, ch.per_order_rate, ch.salary, ch.incentive_per_order, "
    "       ch.incentive_per_day, ch.notes, COALESCE(ch.is_active, 1) AS is_active, "
    "       c.payment_model, "
    "  (SELECT COUNT(*) FROM rider_master r WHERE r.company=h.company AND r.hub=h.hub "
    "     AND r.is_active=1) AS riders, "
    "  (SELECT COUNT(DISTINCT ea.ev_id) FROM ev_assignments ea "
    "     JOIN rider_master r2 ON r2.person_id=ea.person_id "
    "   WHERE ea.returned_date IS NULL AND r2.company=h.company AND r2.hub=h.hub) AS evs "
    "FROM (SELECT DISTINCT company, hub FROM rider_master WHERE hub IS NOT NULL AND hub<>'' "
    "      UNION SELECT company, hub FROM company_hubs) h "
    "LEFT JOIN company_hubs ch ON ch.company=h.company AND ch.hub=h.hub "
    "LEFT JOIN companies c ON c.company_name=h.company "
)


def _row(r) -> HubOut:
    return HubOut(
        company=r["company"],
        hub=r["hub"],
        zone=r["zone"],
        per_order_rate=r["per_order_rate"],
        salary=r["salary"],
        incentive_per_order=r["incentive_per_order"],
        incentive_per_day=r["incentive_per_day"],
        notes=r["notes"],
        is_active=bool(r["is_active"]),
        riders=int(r["riders"] or 0),
        evs=int(r["evs"] or 0),
        payment_model=r["payment_model"],
    )


@router.get("", response_model=list[HubOut])
def list_hubs(
    company: str | None = Query(None),
    _: dict = Depends(get_current_user),
) -> list[HubOut]:
    """Every store seen on a rider row or added by an admin, per company."""
    where, params = "", []
    if company:
        where, params = "WHERE h.company=? ", [company]
    with get_connection() as conn:
        rows = conn.execute(
            _LIST_SQL + where + "ORDER BY h.company, ch.zone IS NULL DESC, ch.zone, h.hub", params
        ).fetchall()
    return [_row(r) for r in rows]


def upsert_hub(conn, company: str, hub: str, body: HubIn, user: dict) -> dict:
    """Create or update one store row. Returns {"before": {...}|None, "after": {...}}."""
    name = hub.strip()
    if not name:
        raise HTTPException(400, "hub is required")
    if not conn.execute("SELECT 1 FROM companies WHERE company_name=?", (company,)).fetchone():
        raise HTTPException(404, f"Company {company!r} not found")
    fields: dict[str, object] = {}
    if "zone" in body.model_fields_set:
        fields["zone"] = normalize_zone(body.zone)
    for k in ("per_order_rate", "salary", "incentive_per_order", "incentive_per_day"):
        if k in body.model_fields_set:
            v = getattr(body, k)
            if v is not None and v < 0:
                raise HTTPException(400, f"{k} cannot be negative")
            fields[k] = None if v is None else to_paise(v)
    if "notes" in body.model_fields_set:
        fields["notes"] = (body.notes or "").strip() or None
    if "is_active" in body.model_fields_set and body.is_active is not None:
        fields["is_active"] = 1 if body.is_active else 0
    before = conn.execute(
        "SELECT zone, per_order_rate, salary, incentive_per_order, incentive_per_day, notes, "
        "is_active FROM company_hubs WHERE company=? AND hub=?",
        (company, name),
    ).fetchone()
    if before is None:
        cols = ["company", "hub", "updated_by"] + list(fields)
        conn.execute(
            f"INSERT INTO company_hubs ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
            [company, name, user["email"], *fields.values()],
        )
    elif fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(
            f"UPDATE company_hubs SET {sets}, updated_at=datetime('now'), updated_by=? "
            "WHERE company=? AND hub=?",
            [*fields.values(), user["email"], company, name],
        )
    after = conn.execute(
        "SELECT zone, per_order_rate, salary, incentive_per_order, incentive_per_day, notes, "
        "is_active FROM company_hubs WHERE company=? AND hub=?",
        (company, name),
    ).fetchone()
    return {"before": dict(before) if before else None, "after": dict(after)}


@router.put("/{company}/{hub}", response_model=HubOut)
def put_hub(company: str, hub: str, body: HubIn, user: dict = Depends(require_admin)) -> HubOut:
    """Set a store's zone and/or pay figures. Any hub name is accepted so a
    store can be prepared before its first rider arrives."""
    with get_connection() as conn:
        change = upsert_hub(conn, company, hub, body, user)
        record_activity(
            conn,
            user,
            "hub.update",
            entity_type="hub",
            entity_id=f"{hub.strip()}@{company}",
            label=hub.strip(),
            details={
                "company": company,
                "changed": diff_fields(
                    change["before"] or {}, change["after"], list(change["after"].keys())
                ),
                "created": change["before"] is None,
            },
        )
        conn.commit()
        row = conn.execute(
            _LIST_SQL + "WHERE h.company=? AND h.hub=?", (company, hub.strip())
        ).fetchone()
    return _row(row)


def store_pay(conn, company: str, hub: str | None) -> dict:
    """The store-level pay figures for a rider's hub (paise), or {} when the
    hub has none set. Used by the per-order and salary cycle builders."""
    if not hub:
        return {}
    r = conn.execute(
        "SELECT per_order_rate, salary, incentive_per_order, incentive_per_day "
        "FROM company_hubs WHERE company=? AND hub=?",
        (company, hub),
    ).fetchone()
    return {k: v for k, v in dict(r).items() if v is not None} if r else {}
