"""Arrears overview: every person with EV-rent and/or COD-pending arrears."""

from __future__ import annotations

from fastapi import Body, APIRouter, Depends

from payout.api.schemas import ExportSelection
from payout.api.auth import get_current_user
from payout.db import get_connection
from payout.exports import xlsx_response

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


@router.post("/export")
def export_arrears(body: ExportSelection = Body(default=ExportSelection()),
                  _: dict = Depends(get_current_user)):
    """Same payload as GET /arrears but as a styled .xlsx download.

    Adds a derived Total Dues column (EV outstanding + Dues carry-forward) so
    the operator can ladder by overall debt at a glance.
    """
    data = list_arrears(_)
    if body.ids is not None:
        idset = {str(x) for x in body.ids}
        data = [r for r in data if str(r["person_id"]) in idset]
    headers = [
        "Person ID", "Name", "Companies", "Hub", "EV ID", "Model",
        "EV Outstanding", "Dues (Carryfwd)", "Total Dues", "Last Updated",
    ]
    rows = [
        (
            r["person_id"], r["display_name"], r["companies"] or "",
            r["hubs"] or "", r["ev_id"] or "", r["model"] or "",
            r["outstanding"], r["dues_outstanding"],
            (r["outstanding"] or 0) + (r["dues_outstanding"] or 0),
            r["last_updated"] or "",
        )
        for r in data
    ]
    return xlsx_response(
        filename_stem="arrears",
        sheet_name="ARREARS",
        headers=headers, rows=rows,
        numeric_cols=(7, 8, 9),
        money_cols=(7, 8, 9),
        totals_cols=(7, 8, 9),
        left_align_cols=(2, 3, 4),
    )
