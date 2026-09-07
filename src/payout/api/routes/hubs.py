"""Hubs and their zones.

Hubs are free text on rider rows (they arrive with company files and
onboarding). This is the one place that says which zone — North or South —
a hub belongs to, so the recruiter app can filter riders and the fleet by
zone. A hub with no zone yet is "unassigned" until an admin sets it here.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from payout.api.auth import get_current_user, require_admin
from payout.db import get_connection
from payout.domain.activity import record_activity

router = APIRouter()

ZONES = ("North", "South")


def zone_filter(zone: str | None) -> str | None:
    """Normalise a ``?zone=`` query value: ``North`` / ``South`` /
    ``unassigned`` (any case) or None; anything else is a 400."""
    z = (zone or "").strip().lower()
    if not z:
        return None
    if z == "unassigned":
        return z
    if z.title() in ZONES:
        return z
    raise HTTPException(400, f"zone must be one of {', '.join(ZONES)} or unassigned")


class HubOut(BaseModel):
    hub: str
    zone: str | None = None
    riders: int = 0  # active rider ids at this hub
    evs: int = 0  # EVs currently held by riders of this hub


class ZoneIn(BaseModel):
    zone: str | None = None  # North | South | null (clear)


@router.get("", response_model=list[HubOut])
def list_hubs(_: dict = Depends(get_current_user)) -> list[HubOut]:
    """Every hub seen on a rider row, with its zone and a couple of counts."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT h.hub, hz.zone, "
            "  (SELECT COUNT(*) FROM rider_master r WHERE r.hub=h.hub AND r.is_active=1) "
            "    AS riders, "
            "  (SELECT COUNT(DISTINCT ea.ev_id) FROM ev_assignments ea "
            "     JOIN rider_master r2 ON r2.person_id=ea.person_id "
            "   WHERE ea.returned_date IS NULL AND r2.hub=h.hub) AS evs "
            "FROM (SELECT DISTINCT hub FROM rider_master WHERE hub IS NOT NULL AND hub<>'' "
            "      UNION SELECT hub FROM hub_zones) h "
            "LEFT JOIN hub_zones hz ON hz.hub=h.hub "
            "ORDER BY hz.zone IS NULL DESC, hz.zone, h.hub"
        ).fetchall()
    return [
        HubOut(hub=r["hub"], zone=r["zone"], riders=int(r["riders"] or 0), evs=int(r["evs"] or 0))
        for r in rows
    ]


@router.put("/{hub}", response_model=HubOut)
def set_zone(hub: str, body: ZoneIn, user: dict = Depends(require_admin)) -> HubOut:
    """Set (or clear) a hub's zone. Any hub name is accepted so a zone can
    be prepared before the first rider arrives at it."""
    name = hub.strip()
    if not name:
        raise HTTPException(400, "hub is required")
    zone = (body.zone or "").strip().title() or None
    if zone is not None and zone not in ZONES:
        raise HTTPException(400, f"zone must be one of {', '.join(ZONES)} (or empty to clear)")
    with get_connection() as conn:
        before = conn.execute("SELECT zone FROM hub_zones WHERE hub=?", (name,)).fetchone()
        if zone is None:
            conn.execute("DELETE FROM hub_zones WHERE hub=?", (name,))
        elif before:
            conn.execute(
                "UPDATE hub_zones SET zone=?, updated_at=datetime('now'), updated_by=? WHERE hub=?",
                (zone, user["email"], name),
            )
        else:
            conn.execute(
                "INSERT INTO hub_zones (hub, zone, updated_by) VALUES (?,?,?)",
                (name, zone, user["email"]),
            )
        record_activity(
            conn,
            user,
            "hub.zone",
            entity_type="hub",
            entity_id=name,
            label=name,
            details={"zone": [before["zone"] if before else None, zone]},
        )
        riders = conn.execute(
            "SELECT COUNT(*) FROM rider_master WHERE hub=? AND is_active=1", (name,)
        ).fetchone()[0]
        conn.commit()
    return HubOut(hub=name, zone=zone, riders=int(riders))
