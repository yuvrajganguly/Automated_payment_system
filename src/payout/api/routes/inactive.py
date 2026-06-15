"""Global Inactive Riders view.

A rider lands here only if EV rent has actually been missed for them — either
their EV-rent arrears are currently outstanding, or at least one RENT_MISSED
transaction has been recorded historically. Per-cycle inactives in the engine
output (the workbook INACTIVE sheet) are scoped to that cycle's company; this
is the cross-company aggregate.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query

from payout.api.auth import get_current_user
from payout.db import get_connection

router = APIRouter()


@router.get("")
def list_inactive_riders(
    days: int = Query(14, ge=1, le=365),
    _: dict = Depends(get_current_user),
) -> list[dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT pr.person_id, pr.display_name,
                   ea.ev_id, ea.handover_date, ea.rent_charged_through,
                   COALESCE(b.current_balance, 0)     AS current_balance,
                   COALESCE(ar.outstanding, 0)        AS arrears_outstanding,
                   COALESCE(ar.total_missed, 0)       AS total_missed,
                   (SELECT MAX(cycle_end) FROM transactions t
                      WHERE t.person_id = pr.person_id
                        AND t.event_type IN ('PAYOUT','RENT','RENT_RECOVERED'))
                    AS last_seen_cycle,
                   (SELECT GROUP_CONCAT(DISTINCT rm.company) FROM rider_master rm
                      WHERE rm.person_id = pr.person_id AND rm.is_active = 1)
                    AS companies,
                   (SELECT GROUP_CONCAT(DISTINCT rm.hub) FROM rider_master rm
                      WHERE rm.person_id = pr.person_id AND rm.is_active = 1
                        AND rm.hub IS NOT NULL AND rm.hub <> '')
                    AS hubs
            FROM person_registry pr
            JOIN ev_assignments ea
              ON ea.person_id = pr.person_id AND ea.returned_date IS NULL
            LEFT JOIN balances b   ON b.person_id  = pr.person_id
            LEFT JOIN ev_arrears ar ON ar.person_id = pr.person_id
            """
        ).fetchall()

    out: list[dict] = []
    for r in rows:
        # Gate: only riders for whom EV rent has actually been missed.
        arr = float(r["arrears_outstanding"] or 0)
        missed_total = float(r["total_missed"] or 0)
        if not (arr > 0 or missed_total > 0):
            continue
        last_seen = r["last_seen_cycle"]
        absent = last_seen is None or last_seen < cutoff
        bal = float(r["current_balance"] or 0)
        reasons: list[str] = []
        if arr > 0:
            reasons.append(f"EV arrears {arr:.0f}")
        if missed_total > arr:
            recovered = missed_total - arr
            reasons.append(f"Previously recovered {recovered:.0f}")
        if absent:
            reasons.append(
                f"Not processed since {last_seen}" if last_seen
                else "Never processed"
            )
        if bal < 0:
            reasons.append(f"Dues {-bal:.0f}")
        out.append({
            "person_id": r["person_id"],
            "display_name": r["display_name"],
            "ev_id": r["ev_id"],
            "handover_date": r["handover_date"],
            "rent_charged_through": r["rent_charged_through"],
            "last_seen_cycle": last_seen,
            "current_balance": bal,
            "arrears_outstanding": arr,
            "total_missed": missed_total,
            "companies": r["companies"] or "",
            "hubs": r["hubs"] or "",
            "reason": "; ".join(reasons),
        })
    out.sort(key=lambda x: (-x["arrears_outstanding"], x["last_seen_cycle"] or ""))
    return out
