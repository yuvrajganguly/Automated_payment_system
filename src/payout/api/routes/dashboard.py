"""Aggregated KPIs for the Dashboard tab.

Cycle filter is an ISO **week_bucket** (e.g. ``2026-W24``) plus an optional
company. All cards/queries scope to "every cycle_end falling inside that
week" — which makes the dashboard correct even when companies' cycles end
on different weekdays (Spencer's Sun, Blitz Sat, etc.).

Endpoints:
  GET /summary                    — headline numbers + chart series.
  GET /breakdown/{metric}         — drill-down list for a single card.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from openpyxl import Workbook

from payout.api.auth import get_current_user
from payout.db import get_connection
from payout.exports import add_styled_sheet, workbook_response
from payout.money import to_rupees

router = APIRouter()


def _split_companies(s: Optional[str]) -> list[str]:
    """Comma-separated company filter → list. Empty / None → empty list."""
    if not s:
        return []
    return [c.strip() for c in s.split(",") if c.strip()]


def _resolve_cycle_ends(conn, companies: list[str],
                        week_bucket: Optional[str]) -> list[str]:
    """Distinct cycle_ends in scope. ``companies=[]`` means all."""
    sql = "SELECT DISTINCT cycle_end FROM company_cycles WHERE 1=1"
    params: list = []
    if companies:
        ph = ",".join("?" for _ in companies)
        sql += f" AND company IN ({ph})"; params.extend(companies)
    if week_bucket:
        sql += " AND week_bucket = ?"; params.append(week_bucket)
    return [r["cycle_end"] for r in conn.execute(sql, params).fetchall()]


def _scope_sql(companies: list[str], cycle_ends: list[str]) -> tuple[str, list]:
    """WHERE fragment that constrains a ``transactions t`` query to scope."""
    parts: list[str] = []
    params: list = []
    if companies:
        ph = ",".join("?" for _ in companies)
        parts.append(f"t.company IN ({ph})"); params.extend(companies)
    if cycle_ends:
        ph = ",".join("?" for _ in cycle_ends)
        parts.append(f"t.cycle_end IN ({ph})"); params.extend(cycle_ends)
    return ((" AND " + " AND ".join(parts)) if parts else "", params)


def _default_window():
    """Default scope when nothing is passed: last 7 days ending today."""
    from datetime import date as _date, timedelta as _td
    today = _date.today()
    return (today - _td(days=6), today)


@router.get("/summary")
def dashboard_summary(
    company: Optional[str] = None,        # legacy single (back-compat)
    companies: Optional[str] = None,      # comma-separated multi
    date_from: Optional[str] = None,      # ISO date — inclusive
    date_to: Optional[str] = None,        # ISO date — inclusive
    # Back-compat: callers using ?week_bucket=YYYY-Www get the week's [Mon, Sun].
    week_bucket: Optional[str] = None,
    _: dict = Depends(get_current_user),
) -> dict:
    cos = _split_companies(companies) or ([company] if company else [])
    from datetime import date as _date, timedelta as _td
    # Resolve the date window.
    if week_bucket and not (date_from or date_to):
        # Translate week_bucket → date window for any old client.
        try:
            y, w = week_bucket.split("-W")
            from datetime import datetime as _dt
            mon = _dt.strptime(f"{y}-W{int(w):02d}-1", "%G-W%V-%u").date()
            d_from, d_to = mon, mon + _td(days=6)
        except Exception:
            d_from, d_to = _default_window()
    elif date_from and date_to:
        try:
            d_from = _date.fromisoformat(date_from)
            d_to   = _date.fromisoformat(date_to)
        except ValueError:
            raise HTTPException(400, "date_from / date_to must be ISO dates.")
    else:
        d_from, d_to = _default_window()
    with get_connection() as conn:
        # ── filter dropdowns ────────────────────────────────────────────
        avail_companies = [
            r["company"] for r in conn.execute(
                "SELECT DISTINCT company FROM company_cycles ORDER BY company"
            ).fetchall()
        ]
        # avail_weeks used to feed the old week-bucket dropdown. Frontend now
        # uses date pickers, so this is empty. Keeping the key in the response
        # for back-compat with any consumer that still iterates it.
        avail_weeks: list[dict] = []

        # ── DATE WINDOW SCOPING ─────────────────────────────────────────
        # All cycle-based metrics now compute by date range. The transactions
        # table is filtered by transactions.created_at — i.e. *when the row was
        # written*, not which cycle it belongs to. That way "last 7 days" means
        # activity that happened in the last 7 days. The earlier "cycle overlap"
        # filter inflated metrics because any cycle whose date range touched
        # the window counted in full.
        df_iso, dt_iso = d_from.isoformat(), d_to.isoformat()
        # created_at uses datetime('now') so we widen the upper bound by a day
        # to capture activity up to end-of-day.
        scope_parts: list[str] = [
            "date(t.created_at) BETWEEN ? AND ?",
        ]
        scope_params: list = [df_iso, dt_iso]
        if cos:
            ph = ",".join("?" for _ in cos)
            scope_parts.append(f"t.company IN ({ph})")
            scope_params.extend(cos)
        scope = " AND " + " AND ".join(scope_parts)

        # ── Company-scoped ledger filter ────────────────────────────────
        # The ledger has no company column, so we scope by the assigned
        # person's rider_master companies. Empty companies → no filter
        # (full fleet).
        led_co_filter = ""
        led_co_params: list = []
        if cos:
            ph = ",".join("?" for _ in cos)
            led_co_filter = (
                f" AND l.assigned_person_id IN ("
                f"   SELECT DISTINCT rm.person_id FROM rider_master rm "
                f"   WHERE rm.company IN ({ph}) AND rm.is_active=1) "
            )
            led_co_params = list(cos)

        # ── Rent metrics from the daily ledger (source of truth) ─────────
        rent_sums = conn.execute(
            f"SELECT "
            f"  COALESCE(SUM(CASE WHEN l.state='billable' THEN l.daily_cost ELSE 0 END), 0) AS expected, "
            f"  COALESCE(SUM(CASE WHEN l.billing_status IN ('billed','recovered') "
            f"                    THEN l.daily_cost ELSE 0 END), 0) AS collected, "
            f"  COALESCE(SUM(CASE WHEN l.billing_status='missed' "
            f"                    THEN l.daily_cost ELSE 0 END), 0) AS missed_day_sum, "
            f"  COALESCE(SUM(CASE WHEN l.billing_status='pending' "
            f"                    OR (l.billing_status IS NULL AND l.state='billable') "
            f"                    THEN l.daily_cost ELSE 0 END), 0) AS pending_day_sum, "
            f"  COALESCE(SUM(l.provider_cost), 0) AS provider_owed "
            f"FROM ev_daily_ledger l "
            f"WHERE l.day BETWEEN ? AND ? {led_co_filter}",
            [df_iso, dt_iso] + led_co_params,
        ).fetchone()
        rent_expected = float(rent_sums["expected"] or 0)
        rent_collected = float(rent_sums["collected"] or 0)
        # 'missed' = rider absent, rent fell to arrears (a real loss).
        # 'pending' = billable days no cycle has processed yet (not a loss,
        # just not collected). Splitting them stops a current, half-run
        # week from looking like missed money.
        rent_missed = float(rent_sums["missed_day_sum"] or 0)
        rent_pending = float(rent_sums["pending_day_sum"] or 0)
        provider_owed = float(rent_sums["provider_owed"] or 0)

        # ── Active / Inactive riders ─────────────────────────────────────
        # Active rider = a person whose person_id has a PAYOUT event in any of
        # their (selected) companies during the window. Otherwise, if they
        # have an active rider_master row in the selected scope, they're
        # inactive (didn't show up anywhere they work).
        co_scope = ""
        co_scope_params: list = []
        if cos:
            ph = ",".join("?" for _ in cos)
            co_scope = f"AND rm.company IN ({ph})"
            co_scope_params = cos
        active_pids = {r["person_id"] for r in conn.execute(
            f"SELECT DISTINCT t.person_id FROM transactions t "
            f"WHERE t.event_type='PAYOUT' {scope}",
            scope_params,
        ).fetchall()}
        # All persons who have an active rider_master row in scope. Inactive
        # is this set minus the active set.
        # Only a company that actually processed a payout in the window can
        # render its riders 'inactive' — otherwise a company that simply
        # did not upload this week marks all its riders absent (false +ve).
        companies_ran = [r["company"] for r in conn.execute(
            f"SELECT DISTINCT t.company FROM transactions t "
            f"WHERE t.event_type='PAYOUT' {scope}",
            scope_params,
        ).fetchall()]
        if companies_ran:
            ran_ph = ",".join("?" for _ in companies_ran)
            scope_pids = {r["person_id"] for r in conn.execute(
                f"SELECT DISTINCT rm.person_id FROM rider_master rm "
                f"WHERE rm.is_active=1 {co_scope} AND rm.company IN ({ran_ph})",
                co_scope_params + list(companies_ran),
            ).fetchall()}
        else:
            scope_pids = set()
        active_riders = len(active_pids)
        inactive_pids = scope_pids - active_pids
        inactive_riders = len(inactive_pids)

        # ── Active / Inactive / Untouched EVs ────────────────────────────
        # Three-bucket reconciliation. The universe is in_use EVs whose
        # current rider works at a selected company (or all in_use EVs if no
        # company filter). Within that universe:
        #   Active  = had any 'billed' or 'recovered' day in the window
        #   Inactive= had any 'missed' day in the window (and not Active)
        #   Untouched = remainder (idle, in maintenance, or no cycle covered them)
        # Active + Inactive + Untouched = in_use ✓
        ev_co_join = ""
        ev_co_params: list = []
        if cos:
            ph = ",".join("?" for _ in cos)
            ev_co_join = (
                f" AND ea.person_id IN ("
                f"   SELECT DISTINCT rm.person_id FROM rider_master rm "
                f"   WHERE rm.company IN ({ph}) AND rm.is_active=1) "
            )
            ev_co_params = list(cos)
        in_use_ev_ids = {r["ev_id"] for r in conn.execute(
            f"SELECT DISTINCT u.ev_id FROM ev_units u "
            f"LEFT JOIN ev_assignments ea ON ea.ev_id=u.ev_id "
            f"                            AND ea.returned_date IS NULL "
            f"WHERE u.status='in_use' "
            f"  AND (? = 0 OR ea.person_id IS NOT NULL) {ev_co_join}",
            [1 if cos else 0] + ev_co_params,
        ).fetchall()}
        active_ev_ids = {r["ev_id"] for r in conn.execute(
            f"SELECT DISTINCT l.ev_id FROM ev_daily_ledger l "
            f"WHERE l.day BETWEEN ? AND ? "
            f"  AND l.billing_status IN ('billed','recovered') {led_co_filter}",
            [df_iso, dt_iso] + led_co_params,
        ).fetchall()} & in_use_ev_ids
        inactive_ev_ids = {r["ev_id"] for r in conn.execute(
            f"SELECT DISTINCT l.ev_id FROM ev_daily_ledger l "
            f"WHERE l.day BETWEEN ? AND ? "
            f"  AND l.billing_status='missed' {led_co_filter}",
            [df_iso, dt_iso] + led_co_params,
        ).fetchall()} & in_use_ev_ids
        inactive_ev_ids = inactive_ev_ids - active_ev_ids
        untouched_ev_ids = in_use_ev_ids - active_ev_ids - inactive_ev_ids
        active_evs = len(active_ev_ids)
        inactive_evs = len(inactive_ev_ids)
        untouched_evs = len(untouched_ev_ids)

        # ── Money flow over the window (from transactions) ───────────────
        sums = conn.execute(
            f"SELECT "
            f" SUM(CASE WHEN t.event_type IN ('RENT_RECOVERED','XC_RENT_RECOVERED') "
            f"          THEN t.amount ELSE 0 END) AS arrears_recovered, "
            f" SUM(CASE WHEN t.event_type='RELEASE'        THEN -t.amount ELSE 0 END) AS payout, "
            f" SUM(CASE WHEN t.event_type='PAYOUT'         THEN  t.amount ELSE 0 END) AS gross_payout, "
            f" SUM(CASE WHEN t.event_type='RENT_COLLECTED' AND "
            f"          (t.created_by IS NOT NULL AND t.created_by NOT IN ('engine','auto')) "
            f"          THEN t.amount ELSE 0 END) AS manual_rent "
            f"FROM transactions t WHERE 1=1 {scope}",
            scope_params,
        ).fetchone()
        arrears_recov   = float(sums["arrears_recovered"] or 0)
        payout          = float(sums["payout"]          or 0)
        gross_payout    = float(sums["gross_payout"]    or 0)
        manual_rent     = float(sums["manual_rent"]     or 0)
        hold = max(0.0, gross_payout - payout)

        # COD: scope by the cod_holds row's created_at — same semantic as
        # transactions (when the row was written), so "last 7 days" means
        # COD holds that landed in the last 7 days.
        cod_params: list = [df_iso, dt_iso]
        cod_filter = "date(ch.created_at) BETWEEN ? AND ?"
        if cos:
            ph = ",".join("?" for _ in cos)
            cod_filter += f" AND ch.company IN ({ph})"; cod_params.extend(cos)
        cod_total = float(conn.execute(
            f"SELECT COALESCE(SUM(ch.amount), 0) AS s FROM cod_holds ch "
            f"WHERE {cod_filter}",
            cod_params,
        ).fetchone()["s"])

        old_dues_now = float(conn.execute(
            "SELECT COALESCE(SUM(-current_balance), 0) AS s FROM balances "
            "WHERE current_balance < 0"
        ).fetchone()["s"])
        ev_arrears_now = float(conn.execute(
            "SELECT COALESCE(SUM(outstanding), 0) AS s FROM ev_arrears"
        ).fetchone()["s"])
        total_arrears = old_dues_now + ev_arrears_now

        stats = {
            "active_riders":     active_riders,
            "inactive_riders":   inactive_riders,
            "active_evs":        active_evs,
            "inactive_evs":      inactive_evs,
            "untouched_evs":     untouched_evs,
            "rent_expected":     round(rent_expected, 2),
            "rent_collected":    round(rent_collected, 2),
            "rent_missed":       round(rent_missed, 2),
            "rent_pending":      round(rent_pending, 2),
            "arrears_recovered": round(arrears_recov, 2),
            "total_arrears":     round(total_arrears, 2),
            "manual_rent":       round(manual_rent, 2),
            "cod":               round(cod_total, 2),
            "hold":              round(hold, 2),
            "payout":            round(payout, 2),
            "provider_owed":     round(provider_owed, 2),
        }

        lifetime = {
            "total_riders": conn.execute(
                "SELECT COUNT(*) AS n FROM person_registry"
            ).fetchone()["n"],
            "total_evs": conn.execute(
                "SELECT COUNT(*) AS n FROM ev_units WHERE status <> 'returned'"
            ).fetchone()["n"],
            "total_payout": round(float(conn.execute(
                "SELECT COALESCE(SUM(-amount), 0) AS s FROM transactions "
                "WHERE event_type='RELEASE'"
            ).fetchone()["s"]), 2),
        }

        # ── charts ──────────────────────────────────────────────────────
        # All riders with dues or arrears, sorted worst-first. Used by both
        # the live "Total Rent Arrears" card breakdown drawer and the
        # dashboard's full arrears list. Scoped by company chip via active
        # rider_master rows so single-company views don't surface unrelated
        # multi-company riders' debts.
        arr_co_filter = ""
        arr_co_params: list = []
        if cos:
            ph = ",".join("?" for _ in cos)
            arr_co_filter = (
                f"AND pr.person_id IN ("
                f"  SELECT DISTINCT rm.person_id FROM rider_master rm "
                f"  WHERE rm.company IN ({ph}) AND rm.is_active=1) "
            )
            arr_co_params = list(cos)
        top_arrears_rows = conn.execute(
            f"""
            SELECT pr.person_id, pr.display_name,
                   COALESCE(ar.outstanding, 0) AS ev_arrears,
                   CASE WHEN COALESCE(b.current_balance, 0) < 0
                        THEN -b.current_balance ELSE 0 END AS dues
            FROM person_registry pr
            LEFT JOIN balances   b  ON b.person_id  = pr.person_id
            LEFT JOIN ev_arrears ar ON ar.person_id = pr.person_id
            WHERE (COALESCE(b.current_balance, 0) < 0
                   OR COALESCE(ar.outstanding, 0) > 0)
              {arr_co_filter}
            ORDER BY (COALESCE(ar.outstanding, 0) +
                      CASE WHEN COALESCE(b.current_balance, 0) < 0
                           THEN -b.current_balance ELSE 0 END) DESC
            """,
            arr_co_params,
        ).fetchall()
        top_arrears = [
            {"person_id": r["person_id"], "name": r["display_name"],
             "ev_arrears": round(float(r["ev_arrears"] or 0), 2),
             "dues": round(float(r["dues"] or 0), 2),
             "total": round(float(r["ev_arrears"] or 0) + float(r["dues"] or 0), 2)}
            for r in top_arrears_rows
        ]
        ev_status = [
            {"status": r["status"], "count": r["n"]}
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM ev_units GROUP BY status"
            ).fetchall()
        ]
        # Trend charts now respect the company chip + date window. They were
        # showing the last N cycles across all companies regardless of filter,
        # which made the chips a no-op on every line.
        chart_co_filter = ""
        chart_co_params: list = []
        if cos:
            ph = ",".join("?" for _ in cos)
            chart_co_filter = f"AND company IN ({ph})"
            chart_co_params = list(cos)
        cyc_rows = conn.execute(
            f"SELECT company, cycle_start, cycle_end, week_bucket, "
            f"       total_release, total_rent_collected, total_rent_missed "
            f"FROM company_cycles "
            f"WHERE cycle_end BETWEEN ? AND ? "
            f"  {chart_co_filter} "
            f"ORDER BY cycle_end ASC, company",
            [df_iso, dt_iso] + chart_co_params,
        ).fetchall()
        releases_by_cycle = [
            {"label": f"{r['cycle_end']} · {r['company']}",
             "value": round(float(r["total_release"] or 0), 2)}
            for r in cyc_rows
        ][-20:]
        rent_collected_by_cycle = [
            {"label": f"{r['cycle_end']} · {r['company']}",
             "value": round(float(r["total_rent_collected"] or 0), 2)}
            for r in cyc_rows
        ][-20:]
        am_chart_co_filter = ""
        if cos:
            am_chart_co_filter = f"AND t.company IN ({','.join('?' for _ in cos)})"
        am_rows = conn.execute(
            f"""
            SELECT t.cycle_end,
                   SUM(CASE WHEN t.event_type IN ('RENT_RECOVERED','XC_RENT_RECOVERED')
                            THEN t.amount ELSE 0 END) AS recovered,
                   SUM(CASE WHEN t.event_type='RENT_MISSED'
                            THEN -t.amount ELSE 0 END) AS added
            FROM transactions t
            WHERE t.event_type IN ('RENT_RECOVERED','XC_RENT_RECOVERED','RENT_MISSED')
              AND t.cycle_end BETWEEN ? AND ?
              {am_chart_co_filter}
            GROUP BY t.cycle_end ORDER BY t.cycle_end ASC
            """,
            [df_iso, dt_iso] + list(cos),
        ).fetchall()
        arrears_movement = [
            {"cycle_end": r["cycle_end"],
             "recovered": round(float(r["recovered"] or 0), 2),
             "added":     round(float(r["added"]     or 0), 2)}
            for r in am_rows
        ][-12:]

        recent_per_company = [
            {"company": r["company"], "cycle_start": r["cycle_start"],
             "cycle_end": r["cycle_end"], "week_bucket": r["week_bucket"],
             "rider_count": r["rider_count"],
             "total_release": round(float(r["total_release"] or 0), 2),
             "total_rent_charged": round(float(r["total_rent_charged"] or 0), 2),
             "total_rent_collected": round(float(r["total_rent_collected"] or 0), 2),
             "total_rent_missed": round(float(r["total_rent_missed"] or 0), 2),
             "processed_at": r["processed_at"]}
            for r in conn.execute(
                "SELECT cc.* FROM company_cycles cc "
                "JOIN (SELECT company, MAX(cycle_end) AS m FROM company_cycles "
                "      GROUP BY company) latest "
                "  ON latest.company = cc.company AND latest.m = cc.cycle_end "
                "ORDER BY cc.company"
            ).fetchall()
        ]

    return {
        "filter": {
            "company": company,           # legacy single (kept for compat)
            "companies": cos,
            "date_from": df_iso,
            "date_to":   dt_iso,
            "available_companies": avail_companies,
            "available_weeks": avail_weeks,   # back-compat
        },
        "window": {
            "from": df_iso,
            "to":   dt_iso,
            "days": (d_to - d_from).days + 1,
        },
        "stats": stats,
        "lifetime": lifetime,
        "charts": {
            "top_arrears": top_arrears,
            "ev_status": ev_status,
            "releases_by_cycle": releases_by_cycle,
            "rent_collected_by_cycle": rent_collected_by_cycle,
            "arrears_movement": arrears_movement,
        },
        "top_arrears_list": top_arrears,
        "recent_cycle_per_company": recent_per_company,
    }


# ─────────────────────────────────────────────────────────────────────────
# Breakdowns — one row-list per stat card. Same scoping rules as /summary.
# ─────────────────────────────────────────────────────────────────────────

_METRICS = {
    "active_riders", "inactive_riders",
    "active_evs", "inactive_evs", "untouched_evs",
    "rent_expected", "rent_collected", "rent_missed", "rent_pending",
    "arrears_recovered", "manual_rent", "cod", "hold", "payout",
    "total_arrears", "provider_owed",
}


@router.get("/breakdown/{metric}")
def dashboard_breakdown(
    metric: str,
    company: Optional[str] = None,
    companies: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    week_bucket: Optional[str] = None,    # back-compat
    limit: int = 500,
    _: dict = Depends(get_current_user),
) -> dict:
    if metric not in _METRICS:
        raise HTTPException(400, f"Unknown metric {metric!r}.")
    cos = _split_companies(companies) or ([company] if company else [])
    from datetime import date as _date, timedelta as _td
    if date_from and date_to:
        try:
            d_from = _date.fromisoformat(date_from)
            d_to   = _date.fromisoformat(date_to)
        except ValueError:
            raise HTTPException(400, "date_from / date_to must be ISO dates.")
    elif week_bucket:
        try:
            y, w = week_bucket.split("-W")
            from datetime import datetime as _dt
            mon = _dt.strptime(f"{y}-W{int(w):02d}-1", "%G-W%V-%u").date()
            d_from, d_to = mon, mon + _td(days=6)
        except Exception:
            d_from, d_to = _default_window()
    else:
        d_from, d_to = _default_window()
    df_iso, dt_iso = d_from.isoformat(), d_to.isoformat()
    with get_connection() as conn:
        # Transactions scoped by created_at — the time the row was actually
        # written. Matches the summary endpoint's "last N days = activity in
        # the last N days" semantic.
        scope_parts = ["date(t.created_at) BETWEEN ? AND ?"]
        scope_params: list = [df_iso, dt_iso]
        # Ledger queries get the same company filter (via assigned_person_id
        # → rider_master) so EV / rent breakdowns track the chip selection.
        led_co_filter = ""
        led_co_params: list = []
        if cos:
            ph = ",".join("?" for _ in cos)
            led_co_filter = (
                f" AND l.assigned_person_id IN ("
                f"   SELECT DISTINCT rm.person_id FROM rider_master rm "
                f"   WHERE rm.company IN ({ph}) AND rm.is_active=1) "
            )
            led_co_params = list(cos)
        if cos:
            ph = ",".join("?" for _ in cos)
            scope_parts.append(f"t.company IN ({ph})")
            scope_params.extend(cos)
        scope = " AND " + " AND ".join(scope_parts)
        rows: list[dict] = []
        columns: list[str] = []
        title: str

        if metric == "active_riders":
            title = "Active riders (had a PAYOUT in the window)"
            columns = ["person_id", "name", "company", "payout", "released"]
            sql = (
                f"SELECT t.person_id, pr.display_name AS name, t.company, "
                f"       SUM(CASE WHEN t.event_type='PAYOUT' THEN t.amount ELSE 0 END) AS payout, "
                f"       SUM(CASE WHEN t.event_type='RELEASE' THEN -t.amount ELSE 0 END) AS released "
                f"FROM transactions t "
                f"JOIN person_registry pr ON pr.person_id=t.person_id "
                f"WHERE t.event_type IN ('PAYOUT','RELEASE') {scope} "
                f"GROUP BY t.person_id, pr.display_name, t.company "
                f"ORDER BY released DESC, payout DESC LIMIT ?"
            )
            rows = [dict(r) for r in conn.execute(sql, scope_params + [limit])]

        elif metric == "inactive_riders":
            title = "Inactive riders (active rider_master row, no payout in window)"
            columns = ["person_id", "name", "companies", "has_open_ev"]
            # Active rider_master rows minus persons who showed up in any
            # PAYOUT in the window. Optionally scoped by companies.
            co_filter = ""; co_params: list = []
            if cos:
                ph = ",".join("?" for _ in cos)
                co_filter = f"AND rm.company IN ({ph})"; co_params = list(cos)
            sql = (
                f"SELECT pr.person_id, pr.display_name AS name, "
                f"       GROUP_CONCAT(DISTINCT rm.company) AS companies, "
                f"       EXISTS (SELECT 1 FROM ev_assignments ea "
                f"               WHERE ea.person_id=pr.person_id "
                f"                 AND ea.returned_date IS NULL) AS has_open_ev "
                f"FROM person_registry pr "
                f"JOIN rider_master rm ON rm.person_id=pr.person_id AND rm.is_active=1 "
                f"WHERE 1=1 {co_filter} "
                f"  AND NOT EXISTS ("
                f"    SELECT 1 FROM transactions t "
                f"    WHERE t.person_id=pr.person_id "
                f"      AND t.event_type='PAYOUT' "
                f"      AND date(t.created_at) BETWEEN ? AND ?"
                + (f" AND t.company IN ({','.join('?' for _ in cos)})" if cos else "")
                + f") "
                f"GROUP BY pr.person_id, pr.display_name "
                f"ORDER BY has_open_ev DESC, pr.display_name "
                f"LIMIT ?"
            )
            params = co_params + [df_iso, dt_iso] + list(cos) + [limit]
            rows = [dict(r) for r in conn.execute(sql, params)]

        elif metric == "rent_expected":
            title = "Rent expected (billable EV-days in window, per EV)"
            columns = ["ev_id", "person_id", "name", "days", "expected"]
            sql = (
                f"SELECT l.ev_id, l.assigned_person_id AS person_id, "
                f"       pr.display_name AS name, "
                f"       COUNT(*) AS days, SUM(l.daily_cost) AS expected "
                f"FROM ev_daily_ledger l "
                f"LEFT JOIN person_registry pr ON pr.person_id=l.assigned_person_id "
                f"WHERE l.day BETWEEN ? AND ? AND l.state='billable' {led_co_filter} "
                f"GROUP BY l.ev_id, l.assigned_person_id, pr.display_name "
                f"ORDER BY expected DESC LIMIT ?"
            )
            rows = [dict(r) for r in conn.execute(
                sql, [df_iso, dt_iso] + led_co_params + [limit])]

        elif metric == "provider_owed":
            title = "Owed to providers (per EV) in window"
            columns = ["ev_id", "provider", "model", "days", "owed"]
            sql = (
                f"SELECT l.ev_id, m.provider, m.model_name AS model, "
                f"       COUNT(*) AS days, SUM(l.provider_cost) AS owed "
                f"FROM ev_daily_ledger l "
                f"JOIN ev_units  u ON u.ev_id=l.ev_id "
                f"JOIN ev_models m ON m.model_id=u.model_id "
                f"WHERE l.day BETWEEN ? AND ? {led_co_filter} "
                f"GROUP BY l.ev_id, m.provider, m.model_name "
                f"ORDER BY owed DESC LIMIT ?"
            )
            rows = [dict(r) for r in conn.execute(
                sql, [df_iso, dt_iso] + led_co_params + [limit])]

        elif metric == "active_evs":
            title = "Active EVs (billed or recovered days in window)"
            columns = ["ev_id", "person_id", "name", "days_billed", "collected"]
            sql = (
                f"SELECT l.ev_id, l.assigned_person_id AS person_id, "
                f"       pr.display_name AS name, "
                f"       SUM(CASE WHEN l.billing_status IN ('billed','recovered') "
                f"                THEN 1 ELSE 0 END) AS days_billed, "
                f"       SUM(CASE WHEN l.billing_status IN ('billed','recovered') "
                f"                THEN l.daily_cost ELSE 0 END) AS collected "
                f"FROM ev_daily_ledger l "
                f"LEFT JOIN person_registry pr ON pr.person_id=l.assigned_person_id "
                f"WHERE l.day BETWEEN ? AND ? "
                f"  AND l.billing_status IN ('billed','recovered') {led_co_filter} "
                f"GROUP BY l.ev_id, l.assigned_person_id, pr.display_name "
                f"ORDER BY collected DESC LIMIT ?"
            )
            rows = [dict(r) for r in conn.execute(
                sql, [df_iso, dt_iso] + led_co_params + [limit])]

        elif metric == "inactive_evs":
            title = "Inactive EVs (missed days in window)"
            columns = ["ev_id", "person_id", "name", "days_missed", "missed_amount"]
            sql = (
                f"SELECT l.ev_id, l.assigned_person_id AS person_id, "
                f"       pr.display_name AS name, "
                f"       SUM(CASE WHEN l.billing_status='missed' THEN 1 ELSE 0 END) AS days_missed, "
                f"       SUM(CASE WHEN l.billing_status='missed' THEN l.daily_cost ELSE 0 END) AS missed_amount "
                f"FROM ev_daily_ledger l "
                f"LEFT JOIN person_registry pr ON pr.person_id=l.assigned_person_id "
                f"WHERE l.day BETWEEN ? AND ? AND l.billing_status='missed' {led_co_filter} "
                f"GROUP BY l.ev_id, l.assigned_person_id, pr.display_name "
                f"ORDER BY missed_amount DESC LIMIT ?"
            )
            rows = [dict(r) for r in conn.execute(
                sql, [df_iso, dt_iso] + led_co_params + [limit])]

        elif metric == "untouched_evs":
            title = "Untouched EVs (in_use, no ledger activity in window)"
            columns = ["ev_id", "person_id", "name", "rent_charged_through",
                       "reason"]
            # EVs with status='in_use' but no rows in ev_daily_ledger over the
            # window. Optionally scoped by the assigned rider's company.
            co_filter = ""; co_params: list = []
            if cos:
                ph = ",".join("?" for _ in cos)
                co_filter = (
                    f" AND ea.person_id IN ("
                    f"   SELECT DISTINCT rm.person_id FROM rider_master rm "
                    f"   WHERE rm.company IN ({ph}) AND rm.is_active=1) "
                )
                co_params = list(cos)
            sql = (
                f"SELECT u.ev_id, ea.person_id, pr.display_name AS name, "
                f"       ea.rent_charged_through "
                f"FROM ev_units u "
                f"LEFT JOIN ev_assignments ea ON ea.ev_id=u.ev_id "
                f"                            AND ea.returned_date IS NULL "
                f"LEFT JOIN person_registry pr ON pr.person_id=ea.person_id "
                f"WHERE u.status='in_use' "
                f"  {co_filter} "
                f"  AND NOT EXISTS ("
                f"    SELECT 1 FROM ev_daily_ledger l "
                f"    WHERE l.ev_id=u.ev_id "
                f"      AND l.day BETWEEN ? AND ?) "
                f"ORDER BY u.ev_id LIMIT ?"
            )
            rows = []
            for r in conn.execute(sql, co_params + [df_iso, dt_iso, limit]):
                d = dict(r)
                if not d["person_id"]:
                    d["reason"] = "Idle — no rider currently holding it"
                elif d["rent_charged_through"] and d["rent_charged_through"] >= dt_iso:
                    d["reason"] = "Meter past window — already pre-billed"
                else:
                    d["reason"] = "No cycle has covered these days yet, or rider has no rider_master row"
                rows.append(d)

        elif metric == "rent_collected":
            title = "Rent collected — per rider (from ledger)"
            columns = ["person_id", "name", "days_collected", "collected"]
            sql = (
                f"SELECT l.assigned_person_id AS person_id, "
                f"       pr.display_name AS name, "
                f"       SUM(CASE WHEN l.billing_status IN ('billed','recovered') "
                f"                THEN 1 ELSE 0 END) AS days_collected, "
                f"       SUM(CASE WHEN l.billing_status IN ('billed','recovered') "
                f"                THEN l.daily_cost ELSE 0 END) AS collected "
                f"FROM ev_daily_ledger l "
                f"JOIN person_registry pr ON pr.person_id=l.assigned_person_id "
                f"WHERE l.day BETWEEN ? AND ? "
                f"  AND l.billing_status IN ('billed','recovered') {led_co_filter} "
                f"GROUP BY l.assigned_person_id, pr.display_name "
                f"ORDER BY collected DESC LIMIT ?"
            )
            rows = [dict(r) for r in conn.execute(
                sql, [df_iso, dt_iso] + led_co_params + [limit])]

        elif metric == "rent_missed":
            title = "Rent missed (rider absent -> arrears) per rider"
            columns = ["person_id", "name", "days_missed", "missed"]
            sql = (
                f"SELECT l.assigned_person_id AS person_id, "
                f"       pr.display_name AS name, "
                f"       SUM(CASE WHEN l.billing_status='missed' THEN 1 ELSE 0 END) AS days_missed, "
                f"       SUM(CASE WHEN l.billing_status='missed' THEN l.daily_cost ELSE 0 END) AS missed "
                f"FROM ev_daily_ledger l "
                f"JOIN person_registry pr ON pr.person_id=l.assigned_person_id "
                f"WHERE l.day BETWEEN ? AND ? AND l.billing_status='missed' {led_co_filter} "
                f"GROUP BY l.assigned_person_id, pr.display_name "
                f"ORDER BY missed DESC LIMIT ?"
            )
            rows = [dict(r) for r in conn.execute(
                sql, [df_iso, dt_iso] + led_co_params + [limit])]

        elif metric == "rent_pending":
            title = "Rent pending - billable days no cycle has processed yet"
            columns = ["person_id", "name", "days_pending", "pending"]
            sql = (
                f"SELECT l.assigned_person_id AS person_id, "
                f"       pr.display_name AS name, "
                f"       SUM(CASE WHEN l.billing_status='pending' "
                f"                OR (l.billing_status IS NULL AND l.state='billable') "
                f"                THEN 1 ELSE 0 END) AS days_pending, "
                f"       SUM(CASE WHEN l.billing_status='pending' "
                f"                OR (l.billing_status IS NULL AND l.state='billable') "
                f"                THEN l.daily_cost ELSE 0 END) AS pending "
                f"FROM ev_daily_ledger l "
                f"JOIN person_registry pr ON pr.person_id=l.assigned_person_id "
                f"WHERE l.day BETWEEN ? AND ? {led_co_filter} "
                f"  AND (l.billing_status='pending' "
                f"       OR (l.billing_status IS NULL AND l.state='billable')) "
                f"GROUP BY l.assigned_person_id, pr.display_name "
                f"ORDER BY pending DESC LIMIT ?"
            )
            rows = [dict(r) for r in conn.execute(
                sql, [df_iso, dt_iso] + led_co_params + [limit])]

        elif metric == "arrears_recovered":
            title = "Old arrears clawed back this cycle"
            columns = ["person_id", "name", "company", "event_type", "amount"]
            sql = (
                f"SELECT t.person_id, pr.display_name AS name, t.company, "
                f"       t.event_type, SUM(t.amount) AS amount "
                f"FROM transactions t "
                f"JOIN person_registry pr ON pr.person_id=t.person_id "
                f"WHERE t.event_type IN ('RENT_RECOVERED','XC_RENT_RECOVERED') {scope} "
                f"GROUP BY t.person_id, pr.display_name, t.company, t.event_type "
                f"ORDER BY amount DESC LIMIT ?"
            )
            rows = [dict(r) for r in conn.execute(sql, scope_params + [limit])]

        elif metric == "manual_rent":
            title = "Manual rent payments this cycle"
            columns = ["person_id", "name", "company", "amount", "created_by", "remarks"]
            sql = (
                f"SELECT t.person_id, pr.display_name AS name, t.company, "
                f"       t.amount, t.created_by, t.remarks "
                f"FROM transactions t "
                f"JOIN person_registry pr ON pr.person_id=t.person_id "
                f"WHERE t.event_type='RENT_COLLECTED' "
                f"  AND t.created_by IS NOT NULL "
                f"  AND t.created_by NOT IN ('engine','auto') "
                f"  {scope} "
                f"ORDER BY t.id DESC LIMIT ?"
            )
            rows = [dict(r) for r in conn.execute(sql, scope_params + [limit])]

        elif metric == "cod":
            title = "COD held this cycle"
            columns = ["rider_id", "person_id", "company", "amount", "order_number", "txn_status"]
            cod_filter = "1=1"
            cod_params: list = []
            if cos:
                ph = ",".join("?" for _ in cos)
                cod_filter += f" AND ch.company IN ({ph})"; cod_params.extend(cos)
            if cycle_ends:
                ph = ",".join("?" for _ in cycle_ends)
                cod_filter += f" AND ch.cycle_end IN ({ph})"
                cod_params.extend(cycle_ends)
            sql = (
                f"SELECT ch.rider_id, ch.person_id, ch.company, ch.amount, "
                f"       ch.order_number, ch.txn_status "
                f"FROM cod_holds ch WHERE {cod_filter} "
                f"ORDER BY ch.amount DESC LIMIT ?"
            )
            rows = [dict(r) for r in conn.execute(sql, cod_params + [limit])]

        elif metric == "hold":
            title = "Riders whose payout was withheld this cycle"
            columns = ["person_id", "name", "company", "payout", "released", "held"]
            sql = (
                f"SELECT t.person_id, pr.display_name AS name, t.company, "
                f"       SUM(CASE WHEN t.event_type='PAYOUT' THEN t.amount ELSE 0 END) AS payout, "
                f"       SUM(CASE WHEN t.event_type='RELEASE' THEN -t.amount ELSE 0 END) AS released "
                f"FROM transactions t "
                f"JOIN person_registry pr ON pr.person_id=t.person_id "
                f"WHERE t.event_type IN ('PAYOUT','RELEASE') {scope} "
                f"GROUP BY t.person_id, pr.display_name, t.company "
                f"HAVING payout > released "
                f"ORDER BY (payout - released) DESC LIMIT ?"
            )
            rows = []
            for r in conn.execute(sql, scope_params + [limit]):
                d = dict(r)
                d["held"] = round((d["payout"] or 0) - (d["released"] or 0), 2)
                rows.append(d)

        elif metric == "payout":
            title = "Cash released to riders this cycle"
            columns = ["person_id", "name", "company", "released"]
            sql = (
                f"SELECT t.person_id, pr.display_name AS name, t.company, "
                f"       SUM(-t.amount) AS released "
                f"FROM transactions t "
                f"JOIN person_registry pr ON pr.person_id=t.person_id "
                f"WHERE t.event_type='RELEASE' {scope} "
                f"GROUP BY t.person_id, pr.display_name, t.company "
                f"ORDER BY released DESC LIMIT ?"
            )
            rows = [dict(r) for r in conn.execute(sql, scope_params + [limit])]

        elif metric == "total_arrears":
            title = "All riders carrying arrears or dues (live)"
            columns = ["person_id", "name", "ev_arrears", "dues", "total"]
            sql = (
                "SELECT pr.person_id, pr.display_name AS name, "
                "       COALESCE(ar.outstanding, 0) AS ev_arrears, "
                "       CASE WHEN COALESCE(b.current_balance, 0) < 0 "
                "            THEN -b.current_balance ELSE 0 END AS dues "
                "FROM person_registry pr "
                "LEFT JOIN balances   b  ON b.person_id  = pr.person_id "
                "LEFT JOIN ev_arrears ar ON ar.person_id = pr.person_id "
                "WHERE COALESCE(b.current_balance, 0) < 0 "
                "   OR COALESCE(ar.outstanding, 0) > 0 "
                "ORDER BY (COALESCE(ar.outstanding, 0) + "
                "          CASE WHEN COALESCE(b.current_balance, 0) < 0 "
                "               THEN -b.current_balance ELSE 0 END) DESC "
                "LIMIT ?"
            )
            for r in conn.execute(sql, [limit]):
                d = dict(r)
                d["total"] = round((d["ev_arrears"] or 0) + (d["dues"] or 0), 2)
                rows.append(d)

        else:
            title = metric
            rows = []
    return {"metric": metric, "title": title, "columns": columns, "rows": rows}


# ─────────────────────────────────────────────────────────────────────────
# Excel report — multi-sheet styled workbook.
# ─────────────────────────────────────────────────────────────────────────

@router.get("/export")
def dashboard_export(
    mode: str = "current",                     # current | range | specific
    companies: Optional[str] = None,
    week_bucket: Optional[str] = None,         # used in mode=current
    from_date: Optional[str] = None,           # used in mode=range
    to_date: Optional[str] = None,             # used in mode=range
    cycle_end: Optional[str] = None,           # used in mode=specific
    cycle_company: Optional[str] = None,       # used in mode=specific
    _: dict = Depends(get_current_user),
):
    """Multi-sheet styled .xlsx report. Scopes:

      mode=current   — week_bucket + companies filter (what the dashboard shows)
      mode=range     — every cycle_end in [from_date, to_date] across companies
      mode=specific  — one exact (cycle_company, cycle_end) pair
    """
    cos = _split_companies(companies)
    with get_connection() as conn:
        # Build the cycle_ends in scope according to mode.
        if mode == "specific":
            if not cycle_end or not cycle_company:
                raise HTTPException(400, "mode=specific needs cycle_end + cycle_company.")
            cos = [cycle_company]
            cycle_ends = [cycle_end]
            scope_label = f"{cycle_company} · {cycle_end}"
        elif mode == "range":
            if not from_date or not to_date:
                raise HTTPException(400, "mode=range needs from_date + to_date.")
            q = "SELECT DISTINCT cycle_end FROM company_cycles WHERE cycle_end BETWEEN ? AND ?"
            qp: list = [from_date, to_date]
            if cos:
                ph = ",".join("?" for _ in cos)
                q += f" AND company IN ({ph})"; qp.extend(cos)
            cycle_ends = [r["cycle_end"] for r in conn.execute(q, qp).fetchall()]
            scope_label = f"{from_date} → {to_date}"
        else:
            # mode=current: use date range from the filter bar, falling back to
            # week_bucket for legacy callers, then "latest cycle per company".
            if from_date and to_date:
                q = "SELECT DISTINCT cycle_end FROM company_cycles WHERE cycle_end BETWEEN ? AND ?"
                qp: list = [from_date, to_date]
                if cos:
                    ph = ",".join("?" for _ in cos)
                    q += f" AND company IN ({ph})"; qp.extend(cos)
                cycle_ends = [r["cycle_end"] for r in conn.execute(q, qp).fetchall()]
                scope_label = (f"{from_date} → {to_date}"
                               + (f" · {', '.join(cos)}" if cos else " · all companies"))
            else:
                cycle_ends = _resolve_cycle_ends(conn, cos, week_bucket)
                scope_label = (
                    f"week {week_bucket}" if week_bucket else "latest week"
                ) + (f" · {', '.join(cos)}" if cos else " · all companies")

        scope, scope_params = _scope_sql(cos, cycle_ends)

        # ── Build the workbook ─────────────────────────────────────────
        wb = Workbook(); wb.remove(wb.active)

        # 1. Overview — the 13 cards
        sums = conn.execute(
            f"SELECT "
            f" COUNT(DISTINCT CASE WHEN t.event_type='PAYOUT' THEN t.person_id END) AS active_riders, "
            f" SUM(CASE WHEN t.event_type='RENT'           THEN -t.amount ELSE 0 END) AS rent_charged, "
            f" SUM(CASE WHEN t.event_type='RENT_COLLECTED' THEN  t.amount ELSE 0 END) AS rent_collected, "
            f" SUM(CASE WHEN t.event_type='RENT_MISSED'    THEN -t.amount ELSE 0 END) AS rent_missed, "
            f" SUM(CASE WHEN t.event_type IN ('RENT_RECOVERED','XC_RENT_RECOVERED') "
            f"          THEN t.amount ELSE 0 END) AS arrears_recovered, "
            f" SUM(CASE WHEN t.event_type='RELEASE'        THEN -t.amount ELSE 0 END) AS payout, "
            f" SUM(CASE WHEN t.event_type='PAYOUT'         THEN  t.amount ELSE 0 END) AS gross, "
            f" SUM(CASE WHEN t.event_type='RENT_COLLECTED' AND "
            f"          (t.created_by IS NOT NULL AND t.created_by NOT IN ('engine','auto')) "
            f"          THEN t.amount ELSE 0 END) AS manual_rent "
            f"FROM transactions t WHERE 1=1 {scope}",
            scope_params,
        ).fetchone()
        cod_filter = "1=1"
        cod_params: list = []
        if cos:
            ph = ",".join("?" for _ in cos)
            cod_filter += f" AND ch.company IN ({ph})"; cod_params.extend(cos)
        if cycle_ends:
            ph = ",".join("?" for _ in cycle_ends)
            cod_filter += f" AND ch.cycle_end IN ({ph})"; cod_params.extend(cycle_ends)
        cod_total = float(conn.execute(
            f"SELECT COALESCE(SUM(ch.amount), 0) AS s FROM cod_holds ch WHERE {cod_filter}",
            cod_params,
        ).fetchone()["s"])
        gross = float(sums["gross"] or 0)
        payout = float(sums["payout"] or 0)
        rent_charged = float(sums["rent_charged"] or 0)
        rent_collected = float(sums["rent_collected"] or 0)
        rent_dues = max(0.0, rent_charged - rent_collected)
        old_dues = float(conn.execute(
            "SELECT COALESCE(SUM(-current_balance),0) AS s FROM balances "
            "WHERE current_balance < 0"
        ).fetchone()["s"])
        ev_arr = float(conn.execute(
            "SELECT COALESCE(SUM(outstanding),0) AS s FROM ev_arrears"
        ).fetchone()["s"])

        add_styled_sheet(
            wb,
            sheet_name="Overview",
            headers=["Metric", "Value"],
            rows=[
                ("Scope", scope_label),
                ("Cycle ends included", ", ".join(cycle_ends) or "—"),
                ("Active Riders", sums["active_riders"] or 0),
                ("Rent Charged",      to_rupees(rent_charged)),
                ("Rent Collected",    to_rupees(rent_collected)),
                ("Rent Dues (shortfall)", to_rupees(rent_dues)),
                ("Rent Missed",       to_rupees(float(sums["rent_missed"] or 0))),
                ("Arrears Recovered", to_rupees(float(sums["arrears_recovered"] or 0))),
                ("Manual Rent",       to_rupees(float(sums["manual_rent"] or 0))),
                ("COD",               to_rupees(cod_total)),
                ("HOLD (gross − net)", to_rupees(max(0.0, gross - payout))),
                ("Payout (released)", to_rupees(payout)),
                ("— Live —", ""),
                ("Total EV arrears (live)", to_rupees(ev_arr)),
                ("Total general dues (live)", to_rupees(old_dues)),
                ("Total arrears (EV + dues)", to_rupees(ev_arr + old_dues)),
            ],
            numeric_cols=(2,),
            left_align_cols=(1,),
        )

        # 2. EV Rent: Collected vs Expected per rider (MAIN FOCUS)
        rows_evrent = list(conn.execute(
            f"SELECT t.person_id, pr.display_name AS name, t.company, "
            f"       (SELECT ea.ev_id FROM ev_assignments ea "
            f"          WHERE ea.person_id=t.person_id AND ea.returned_date IS NULL "
            f"          LIMIT 1) AS ev_id, "
            f"       SUM(CASE WHEN t.event_type='RENT'         THEN -t.amount ELSE 0 END) AS expected, "
            f"       SUM(CASE WHEN t.event_type='RENT_COLLECTED' THEN  t.amount ELSE 0 END) AS collected, "
            f"       SUM(CASE WHEN t.event_type='RENT_MISSED'  THEN -t.amount ELSE 0 END) AS missed, "
            f"       SUM(CASE WHEN t.event_type IN ('RENT_RECOVERED','XC_RENT_RECOVERED') "
            f"                THEN t.amount ELSE 0 END) AS recovered "
            f"FROM transactions t "
            f"JOIN person_registry pr ON pr.person_id=t.person_id "
            f"WHERE t.event_type IN ('RENT','RENT_COLLECTED','RENT_MISSED', "
            f"                       'RENT_RECOVERED','XC_RENT_RECOVERED') {scope} "
            f"GROUP BY t.person_id, pr.display_name, t.company "
            f"ORDER BY expected DESC, missed DESC",
            scope_params,
        ))
        add_styled_sheet(
            wb,
            sheet_name="EV Rent vs Expected",
            headers=["Person ID", "Name", "Company", "EV ID",
                     "Expected", "Collected", "Shortfall (Exp − Col)",
                     "Missed (absent)", "Arrears Recovered"],
            rows=[
                (r["person_id"], r["name"], r["company"], r["ev_id"] or "",
                 float(r["expected"] or 0), float(r["collected"] or 0),
                 max(0.0, float(r["expected"] or 0) - float(r["collected"] or 0)),
                 float(r["missed"] or 0), float(r["recovered"] or 0))
                for r in rows_evrent
            ],
            numeric_cols=(5, 6, 7, 8, 9),
            totals_cols=(5, 6, 7, 8, 9),
            money_cols=(5, 6, 7, 8, 9),
            left_align_cols=(2,),
        )

        # 3. All riders with arrears or dues (MAIN FOCUS, live)
        arr_rows = list(conn.execute(
            """
            SELECT pr.person_id, pr.display_name,
                   COALESCE(ar.outstanding, 0) AS ev_arrears,
                   CASE WHEN COALESCE(b.current_balance, 0) < 0
                        THEN -b.current_balance ELSE 0 END AS dues,
                   (SELECT GROUP_CONCAT(DISTINCT rm.company) FROM rider_master rm
                      WHERE rm.person_id = pr.person_id AND rm.is_active=1) AS companies,
                   (SELECT GROUP_CONCAT(DISTINCT rm.hub) FROM rider_master rm
                      WHERE rm.person_id = pr.person_id AND rm.hub IS NOT NULL
                        AND rm.hub <> '') AS hubs
            FROM person_registry pr
            LEFT JOIN balances   b  ON b.person_id  = pr.person_id
            LEFT JOIN ev_arrears ar ON ar.person_id = pr.person_id
            WHERE COALESCE(b.current_balance, 0) < 0
               OR COALESCE(ar.outstanding, 0) > 0
            ORDER BY (COALESCE(ar.outstanding, 0) +
                      CASE WHEN COALESCE(b.current_balance, 0) < 0
                           THEN -b.current_balance ELSE 0 END) DESC
            """
        ))
        add_styled_sheet(
            wb,
            sheet_name="Riders in Arrears",
            headers=["Person ID", "Name", "Companies", "Hub",
                     "EV Arrears", "Dues (Carryfwd)", "Total"],
            rows=[
                (r["person_id"], r["display_name"], r["companies"] or "",
                 r["hubs"] or "",
                 float(r["ev_arrears"]), float(r["dues"]),
                 float(r["ev_arrears"]) + float(r["dues"]))
                for r in arr_rows
            ],
            numeric_cols=(5, 6, 7),
            money_cols=(5, 6, 7),
            totals_cols=(5, 6, 7),
            left_align_cols=(2, 3, 4),
        )

        # 4. Active EVs
        active_ev_rows = list(conn.execute(
            f"SELECT ea.ev_id, ea.person_id, pr.display_name AS name, t.company, "
            f"       SUM(CASE WHEN t.event_type='RENT' THEN -t.amount ELSE 0 END) AS rent, "
            f"       SUM(CASE WHEN t.event_type='RENT_COLLECTED' THEN t.amount ELSE 0 END) AS collected "
            f"FROM ev_assignments ea "
            f"JOIN transactions t ON t.person_id=ea.person_id "
            f"JOIN person_registry pr ON pr.person_id=ea.person_id "
            f"WHERE ea.returned_date IS NULL AND t.event_type='RENT' {scope} "
            f"GROUP BY ea.ev_id, ea.person_id, pr.display_name, t.company "
            f"ORDER BY rent DESC",
            scope_params,
        ))
        add_styled_sheet(
            wb, sheet_name="Active EVs",
            headers=["EV ID", "Person ID", "Name", "Company", "Rent", "Collected"],
            rows=[(r["ev_id"], r["person_id"], r["name"], r["company"],
                   float(r["rent"] or 0), float(r["collected"] or 0))
                  for r in active_ev_rows],
            numeric_cols=(5, 6), totals_cols=(5, 6), money_cols=(5, 6), left_align_cols=(3,),
        )

        # 5. Inactive EVs
        inactive_ev_rows = list(conn.execute(
            f"SELECT ea.ev_id, ea.person_id, pr.display_name AS name, t.company, "
            f"       SUM(-t.amount) AS missed "
            f"FROM ev_assignments ea "
            f"JOIN transactions t ON t.person_id=ea.person_id "
            f"JOIN person_registry pr ON pr.person_id=ea.person_id "
            f"WHERE ea.returned_date IS NULL AND t.event_type='RENT_MISSED' {scope} "
            f"GROUP BY ea.ev_id, ea.person_id, pr.display_name, t.company "
            f"ORDER BY missed DESC",
            scope_params,
        ))
        add_styled_sheet(
            wb, sheet_name="Inactive EVs",
            headers=["EV ID", "Person ID", "Name", "Company", "Missed"],
            rows=[(r["ev_id"], r["person_id"], r["name"], r["company"],
                   float(r["missed"] or 0)) for r in inactive_ev_rows],
            numeric_cols=(5,), totals_cols=(5,), money_cols=(5,), left_align_cols=(3,),
        )

        # 6. Money flow per rider
        money_rows = list(conn.execute(
            f"SELECT t.person_id, pr.display_name AS name, t.company, "
            f" SUM(CASE WHEN t.event_type='PAYOUT'  THEN t.amount ELSE 0 END) AS gross, "
            f" SUM(CASE WHEN t.event_type='RELEASE' THEN -t.amount ELSE 0 END) AS released, "
            f" SUM(CASE WHEN t.event_type='RENT'    THEN -t.amount ELSE 0 END) AS rent, "
            f" SUM(CASE WHEN t.event_type IN ('RENT_RECOVERED','XC_RENT_RECOVERED') "
            f"          THEN t.amount ELSE 0 END) AS recovered, "
            f" SUM(CASE WHEN t.event_type='RENT_COLLECTED' AND "
            f"          (t.created_by IS NOT NULL AND t.created_by NOT IN ('engine','auto')) "
            f"          THEN t.amount ELSE 0 END) AS manual_rent "
            f"FROM transactions t "
            f"JOIN person_registry pr ON pr.person_id=t.person_id "
            f"WHERE t.event_type IN ('PAYOUT','RELEASE','RENT','RENT_RECOVERED', "
            f"                       'XC_RENT_RECOVERED','RENT_COLLECTED') {scope} "
            f"GROUP BY t.person_id, pr.display_name, t.company "
            f"HAVING gross > 0 OR rent > 0 OR recovered > 0 OR manual_rent > 0 "
            f"ORDER BY gross DESC",
            scope_params,
        ))
        add_styled_sheet(
            wb, sheet_name="Money Flow",
            headers=["Person ID", "Name", "Company",
                     "Gross Payout", "Released", "Held",
                     "Rent Charged", "Arrears Recovered", "Manual Rent"],
            rows=[(
                r["person_id"], r["name"], r["company"],
                float(r["gross"] or 0), float(r["released"] or 0),
                max(0.0, float(r["gross"] or 0) - float(r["released"] or 0)),
                float(r["rent"] or 0), float(r["recovered"] or 0),
                float(r["manual_rent"] or 0),
            ) for r in money_rows],
            numeric_cols=(4, 5, 6, 7, 8, 9),
            totals_cols=(4, 5, 6, 7, 8, 9),
            money_cols=(4, 5, 6, 7, 8, 9),
            left_align_cols=(2,),
        )

        # 7. Manual rent payments — useful audit trail
        manual_rows = list(conn.execute(
            f"SELECT t.id, t.person_id, pr.display_name AS name, t.company, "
            f"       t.cycle_start, t.cycle_end, t.amount, t.remarks, "
            f"       t.created_by, t.created_at "
            f"FROM transactions t "
            f"JOIN person_registry pr ON pr.person_id=t.person_id "
            f"WHERE t.event_type='RENT_COLLECTED' AND t.created_by IS NOT NULL "
            f"  AND t.created_by NOT IN ('engine','auto') {scope} "
            f"ORDER BY t.id DESC",
            scope_params,
        ))
        add_styled_sheet(
            wb, sheet_name="Manual Rent Payments",
            headers=["Txn ID", "Person ID", "Name", "Company",
                     "Cycle Start", "Cycle End", "Amount", "Remarks",
                     "Logged by", "At"],
            rows=[(r["id"], r["person_id"], r["name"], r["company"],
                   r["cycle_start"], r["cycle_end"], float(r["amount"] or 0),
                   r["remarks"] or "", r["created_by"] or "",
                   r["created_at"] or "") for r in manual_rows],
            numeric_cols=(7,), totals_cols=(7,), money_cols=(7,), left_align_cols=(3, 8, 9, 10),
        )

        # 8. COD details
        cod_rows = list(conn.execute(
            f"SELECT ch.rider_id, ch.person_id, ch.company, ch.cycle_start, "
            f"       ch.cycle_end, ch.amount, ch.order_number, ch.payment_mode, "
            f"       ch.txn_status, ch.cleared_at, ch.cleared_by "
            f"FROM cod_holds ch WHERE {cod_filter}",
            cod_params,
        ))
        add_styled_sheet(
            wb, sheet_name="COD",
            headers=["Rider ID", "Person ID", "Company", "Cycle Start",
                     "Cycle End", "Amount", "Order #", "Mode", "Status",
                     "Cleared At", "Cleared By"],
            rows=[(r["rider_id"], r["person_id"], r["company"],
                   r["cycle_start"], r["cycle_end"], float(r["amount"] or 0),
                   r["order_number"] or "", r["payment_mode"] or "",
                   r["txn_status"] or "", r["cleared_at"] or "",
                   r["cleared_by"] or "") for r in cod_rows],
            numeric_cols=(6,), totals_cols=(6,), money_cols=(6,), left_align_cols=(7, 8, 9, 11),
        )

        # 9. Per-company cycle history (full)
        cyc_history = list(conn.execute(
            "SELECT company, cycle_start, cycle_end, week_bucket, rider_count, "
            "       riders_paid, riders_in_dues, total_release, "
            "       total_rent_charged, total_rent_collected, total_rent_missed, "
            "       processed_at, processed_by "
            "FROM company_cycles ORDER BY cycle_end DESC, company"
        ))
        add_styled_sheet(
            wb, sheet_name="Cycle History",
            headers=["Company", "Cycle Start", "Cycle End", "Week",
                     "Riders", "Riders Paid", "Riders in Dues",
                     "Released", "Rent Charged", "Rent Collected",
                     "Rent Missed", "Processed At", "Processed By"],
            rows=[(r["company"], r["cycle_start"], r["cycle_end"],
                   r["week_bucket"], r["rider_count"], r["riders_paid"],
                   r["riders_in_dues"], float(r["total_release"] or 0),
                   float(r["total_rent_charged"] or 0),
                   float(r["total_rent_collected"] or 0),
                   float(r["total_rent_missed"] or 0),
                   r["processed_at"], r["processed_by"]) for r in cyc_history],
            numeric_cols=(8, 9, 10, 11),
            money_cols=(8, 9, 10, 11),
            left_align_cols=(12, 13),
        )

    stem = f"dashboard_{mode}"
    return workbook_response(wb, stem)
