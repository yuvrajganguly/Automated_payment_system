"""Aggregated KPIs for the Dashboard tab.

Every metric here is derived from existing tables; nothing is materialised.
That keeps the dashboard honest — it always reflects the live ledger — at
the cost of a few SQL aggregates per page load. With < a hundred cycles and
~300 riders these are cheap on SQLite.

Returned shape:
{
  "kpis":           { active_riders, active_evs, ev_arrears, gen_dues, cod_pending, released_to_date },
  "cycles":         [{ company, cycle_start, cycle_end, released, rent_charged, rent_missed, cod_held, cycle_id }],
  "ev_status":      { in_use, spare, returned, maintenance },
  "top_owing":      [{ person_id, display_name, dues, ev_arrears, cod, total }],
  "recovery_trend": [{ cycle_end, recovered }]
}
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from payout.api.auth import get_current_user
from payout.db import get_connection

router = APIRouter()


@router.get("/summary")
def dashboard_summary(_: dict = Depends(get_current_user)) -> dict:
    with get_connection() as conn:
        # ── headline KPIs ──────────────────────────────────────────────────
        active_riders = conn.execute(
            "SELECT COUNT(*) AS n FROM rider_master WHERE is_active = 1"
        ).fetchone()["n"]
        ev_in_use = conn.execute(
            "SELECT COUNT(*) AS n FROM ev_units WHERE status = 'in_use'"
        ).fetchone()["n"]
        gen_dues = conn.execute(
            "SELECT COALESCE(SUM(-current_balance), 0) AS s FROM balances "
            "WHERE current_balance < 0"
        ).fetchone()["s"]
        ev_arrears = conn.execute(
            "SELECT COALESCE(SUM(outstanding), 0) AS s FROM ev_arrears"
        ).fetchone()["s"]
        cod_pending = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS s FROM cod_holds "
            "WHERE cleared_at IS NULL"
        ).fetchone()["s"]
        released_to_date = conn.execute(
            "SELECT COALESCE(SUM(-amount), 0) AS s FROM transactions "
            "WHERE event_type = 'RELEASE'"
        ).fetchone()["s"]

        # ── per-cycle history (last 20 cycles, newest first) ───────────────
        cycle_rows = conn.execute(
            """
            SELECT t.company, t.cycle_start, t.cycle_end,
                   SUM(CASE WHEN t.event_type='RELEASE'        THEN -t.amount ELSE 0 END) AS released,
                   SUM(CASE WHEN t.event_type='RENT_COLLECTED' THEN  t.amount ELSE 0 END) AS rent_collected,
                   SUM(CASE WHEN t.event_type='RENT'           THEN -t.amount ELSE 0 END) AS rent_charged,
                   SUM(CASE WHEN t.event_type='RENT_MISSED'    THEN -t.amount ELSE 0 END) AS rent_missed,
                   (SELECT COALESCE(SUM(amount), 0) FROM cod_holds ch
                     WHERE ch.company=t.company AND ch.cycle_start=t.cycle_start
                       AND ch.cycle_end=t.cycle_end) AS cod_held
            FROM transactions t
            WHERE t.event_type IN ('RELEASE','RENT','RENT_COLLECTED','RENT_MISSED')
            GROUP BY t.company, t.cycle_start, t.cycle_end
            ORDER BY t.cycle_end DESC, t.company
            LIMIT 40
            """
        ).fetchall()
        cycles = [
            {
                "company": r["company"],
                "cycle_start": r["cycle_start"],
                "cycle_end": r["cycle_end"],
                "released": round(float(r["released"] or 0), 2),
                "rent_collected": round(float(r["rent_collected"] or 0), 2),
                "rent_charged": round(float(r["rent_charged"] or 0), 2),
                "rent_missed": round(float(r["rent_missed"] or 0), 2),
                "cod_held": round(float(r["cod_held"] or 0), 2),
            }
            for r in cycle_rows
        ]

        # ── EV status pie ──────────────────────────────────────────────────
        ev_status_rows = conn.execute(
            "SELECT status, COUNT(*) AS n FROM ev_units GROUP BY status"
        ).fetchall()
        ev_status = {r["status"]: r["n"] for r in ev_status_rows}

        # ── Top 10 riders by total amount owed ─────────────────────────────
        top_rows = conn.execute(
            """
            SELECT pr.person_id, pr.display_name,
                   CASE WHEN COALESCE(b.current_balance, 0) < 0
                        THEN -b.current_balance ELSE 0 END AS dues,
                   COALESCE(ar.outstanding, 0)            AS ev_arrears,
                   COALESCE((SELECT SUM(amount) FROM cod_holds ch
                              WHERE ch.person_id = pr.person_id
                                AND ch.cleared_at IS NULL), 0) AS cod
            FROM person_registry pr
            LEFT JOIN balances   b  ON b.person_id  = pr.person_id
            LEFT JOIN ev_arrears ar ON ar.person_id = pr.person_id
            WHERE COALESCE(b.current_balance, 0) < 0
               OR COALESCE(ar.outstanding, 0) > 0
               OR EXISTS (SELECT 1 FROM cod_holds ch2
                           WHERE ch2.person_id = pr.person_id
                             AND ch2.cleared_at IS NULL)
            ORDER BY (dues + ev_arrears + cod) DESC
            LIMIT 10
            """
        ).fetchall()
        top_owing = [
            {
                "person_id": r["person_id"], "display_name": r["display_name"],
                "dues": round(float(r["dues"] or 0), 2),
                "ev_arrears": round(float(r["ev_arrears"] or 0), 2),
                "cod": round(float(r["cod"] or 0), 2),
                "total": round(float((r["dues"] or 0) + (r["ev_arrears"] or 0) + (r["cod"] or 0)), 2),
            }
            for r in top_rows
        ]

        # ── Recovery trend (XC + arrears recovered per cycle_end) ──────────
        recov_rows = conn.execute(
            """
            SELECT cycle_end, SUM(amount) AS recovered
            FROM transactions
            WHERE event_type IN ('XC_RENT_RECOVERED','RENT_RECOVERED')
            GROUP BY cycle_end
            ORDER BY cycle_end DESC
            LIMIT 12
            """
        ).fetchall()
        recovery_trend = [
            {"cycle_end": r["cycle_end"], "recovered": round(float(r["recovered"] or 0), 2)}
            for r in reversed(recov_rows)
        ]

    return {
        "kpis": {
            "active_riders":     active_riders,
            "active_evs":        ev_in_use,
            "gen_dues":          round(float(gen_dues), 2),
            "ev_arrears":        round(float(ev_arrears), 2),
            "cod_pending":       round(float(cod_pending), 2),
            "released_to_date":  round(float(released_to_date), 2),
        },
        "cycles":         cycles,
        "ev_status":      ev_status,
        "top_owing":      top_owing,
        "recovery_trend": recovery_trend,
    }
