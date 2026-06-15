"""Arrears overview: every person with EV-rent and/or COD-pending arrears."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from payout.api.auth import get_current_user
from payout.db import get_connection

router = APIRouter()


@router.get("")
def list_arrears(_: dict = Depends(get_current_user)) -> list[dict]:
    """All persons with money owed in any bucket: EV-rent, COD, or general
    dues (carryforward from prior cycles).

    Dues are reported as a positive ``dues_outstanding`` (= -current_balance
    when it's negative). The Arrears page uses this to surface carryforward
    riders alongside the EV-rent and COD buckets.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT pr.person_id, pr.display_name, "
            "       a.ev_id, m.model_name AS model, "
            "       COALESCE(ea.total_missed, 0)    AS total_missed, "
            "       COALESCE(ea.total_recovered, 0) AS total_recovered, "
            "       COALESCE(ea.outstanding, 0)     AS outstanding, "
            "       COALESCE(ea.cod_missed, 0)      AS cod_missed, "
            "       COALESCE(ea.cod_recovered, 0)   AS cod_recovered, "
            "       COALESCE(ea.cod_outstanding, 0) AS cod_outstanding, "
            "       CASE WHEN COALESCE(b.current_balance, 0) < 0 "
            "            THEN -b.current_balance ELSE 0 END AS dues_outstanding, "
            "       (SELECT GROUP_CONCAT(DISTINCT rm.company) FROM rider_master rm "
            "        WHERE rm.person_id = pr.person_id AND rm.is_active = 1) AS companies, "
            "       (SELECT GROUP_CONCAT(DISTINCT rm.hub) FROM rider_master rm "
            "        WHERE rm.person_id = pr.person_id AND rm.is_active = 1 "
            "          AND rm.hub IS NOT NULL AND rm.hub <> '') AS hubs, "
            "       COALESCE(ea.last_updated, b.last_updated) AS last_updated "
            "FROM person_registry pr "
            "LEFT JOIN ev_arrears ea ON ea.person_id = pr.person_id "
            "LEFT JOIN balances   b  ON b.person_id  = pr.person_id "
            "LEFT JOIN ev_assignments a ON a.person_id = pr.person_id AND a.returned_date IS NULL "
            "LEFT JOIN ev_units  u ON u.ev_id    = a.ev_id "
            "LEFT JOIN ev_models m ON m.model_id = u.model_id "
            "WHERE COALESCE(ea.outstanding, 0) > 0 "
            "   OR COALESCE(ea.cod_outstanding, 0) > 0 "
            "   OR COALESCE(b.current_balance, 0) < 0 "
            "ORDER BY (COALESCE(ea.outstanding,0) + COALESCE(ea.cod_outstanding,0) "
            "        + CASE WHEN COALESCE(b.current_balance,0)<0 "
            "               THEN -b.current_balance ELSE 0 END) DESC"
        ).fetchall()
    return [dict(r) for r in rows]
