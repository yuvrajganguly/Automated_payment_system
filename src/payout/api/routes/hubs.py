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
