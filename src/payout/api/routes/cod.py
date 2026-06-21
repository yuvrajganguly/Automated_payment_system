"""COD-pending overview + clearance.

Every rider with at least one un-cleared ``cod_holds`` entry shows up here with
their total pending COD, the most recent payout we released to them, and a
breakdown of the individual entries. Marking a rider's COD as cleared closes
the entries and optionally posts a ledger adjustment to credit / debit the
person's general balance.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from payout.api.auth import get_current_user, require_admin
from payout.db import get_connection
from payout.domain.adjustments import post_adjustment
from payout.exports import xlsx_response

router = APIRouter()


@router.get("")
def list_cod(_: dict = Depends(get_current_user)) -> list[dict]:
    """Per-person summary of all pending COD entries."""
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT pr.person_id, pr.display_name,
                   COALESCE(SUM(ch.amount), 0)     AS total_pending,
                   COUNT(ch.id)                    AS entry_count,
                   MIN(ch.cycle_start)             AS earliest_cycle_start,
                   MAX(ch.cycle_end)               AS latest_cycle_end,
                   (SELECT GROUP_CONCAT(DISTINCT ch2.company) FROM cod_holds ch2
                      WHERE ch2.person_id = pr.person_id AND ch2.cleared_at IS NULL)
                                                   AS companies,
                   (SELECT GROUP_CONCAT(DISTINCT rm.hub) FROM rider_master rm
                      WHERE rm.person_id = pr.person_id AND rm.hub IS NOT NULL
                        AND rm.hub <> '')          AS hubs,
                   (SELECT -t.amount FROM transactions t
                      WHERE t.person_id = pr.person_id AND t.event_type = 'RELEASE'
                      ORDER BY t.id DESC LIMIT 1)  AS recent_payout,
                   (SELECT t.cycle_end FROM transactions t
                      WHERE t.person_id = pr.person_id AND t.event_type = 'RELEASE'
                      ORDER BY t.id DESC LIMIT 1)  AS recent_payout_cycle
            FROM cod_holds ch
            JOIN person_registry pr ON pr.person_id = ch.person_id
            WHERE ch.cleared_at IS NULL
            GROUP BY pr.person_id, pr.display_name
            HAVING total_pending > 0
            ORDER BY total_pending DESC
            """
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/export")
def export_cod(_: dict = Depends(get_current_user)):
    """COD page as a styled .xlsx download."""
    data = list_cod(_)
    headers = ["Person ID", "Name", "Companies", "Hub", "Pending Total",
               "Entries", "Earliest Cycle", "Latest Cycle",
               "Recent Payout", "Recent Cycle"]
    rows = [
        (r["person_id"], r["display_name"], r["companies"] or "",
         r["hubs"] or "", r["total_pending"], r["entry_count"],
         r["earliest_cycle_start"] or "", r["latest_cycle_end"] or "",
         r["recent_payout"] or 0, r["recent_payout_cycle"] or "")
        for r in data
    ]
    return xlsx_response(
        filename_stem="cod_pending", sheet_name="COD",
        headers=headers, rows=rows,
        numeric_cols=(5, 9), totals_cols=(5,),
        left_align_cols=(2, 3, 4),
    )


@router.get("/{person_id}/entries")
def list_cod_entries(person_id: int,
                     _: dict = Depends(get_current_user)) -> list[dict]:
    """Line-item COD entries for one person (pending and cleared)."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, cycle_start, cycle_end, company, rider_id, order_number, "
            "       amount, payment_mode, txn_status, source, cleared_at, cleared_by "
            "FROM cod_holds WHERE person_id = ? "
            "ORDER BY cleared_at IS NULL DESC, cycle_end DESC, id DESC",
            (person_id,),
        ).fetchall()
    return [dict(r) for r in rows]


class CodClearIn(BaseModel):
    person_id: int
    entry_ids: Optional[list[int]] = None      # default: all pending entries
    ledger_amount: Optional[float] = None      # > 0 credit, < 0 debit
    reason: Optional[str] = None


@router.post("/clear")
def clear_cod(body: CodClearIn, user: dict = Depends(require_admin)) -> dict:
    """Mark COD entries as cleared. Optionally post a ledger adjustment so the
    rider's general balance reflects the cash collected (positive amount =
    credit, negative = debit)."""
    cleared_at = date.today().isoformat()
    with get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM person_registry WHERE person_id=?", (body.person_id,)
        ).fetchone():
            raise HTTPException(404, f"Person {body.person_id} not found")

        if body.entry_ids:
            placeholders = ",".join("?" * len(body.entry_ids))
            params = [cleared_at, user["email"], body.person_id, *body.entry_ids]
            cur = conn.execute(
                f"UPDATE cod_holds SET cleared_at=?, cleared_by=? "
                f"WHERE person_id=? AND cleared_at IS NULL AND id IN ({placeholders})",
                params,
            )
        else:
            cur = conn.execute(
                "UPDATE cod_holds SET cleared_at=?, cleared_by=? "
                "WHERE person_id=? AND cleared_at IS NULL",
                (cleared_at, user["email"], body.person_id),
            )
        entries_cleared = cur.rowcount

        new_balance = None
        adj_amount = body.ledger_amount or 0.0
        if adj_amount:
            reason = body.reason or f"COD clearance ({entries_cleared} entry/-ies)"
            new_balance = post_adjustment(
                conn, body.person_id, adj_amount, reason, user["email"],
                rider_id="", company="",
            )
        conn.commit()
    return {
        "person_id": body.person_id,
        "entries_cleared": entries_cleared,
        "ledger_amount": adj_amount,
        "new_balance": new_balance,
    }
