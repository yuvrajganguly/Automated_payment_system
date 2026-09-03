"""Dashboard analytics: time series and deep-dive aggregates.

Four read-only endpoints feeding the tabbed dashboard:

  GET /trends      — weekly money-flow series (gross, released, rent
                     collected/missed, arrears recovered, dues delta).
  GET /collection  — rent collection efficiency per week, arrears aging
                     buckets, recovery velocity, COD exposure.
  GET /fleet       — per-EV and per-provider economics from the daily ledger
                     (earned vs provider cost, utilization, idle days).
  GET /riders      — rider movement per week (paid / new / churned), top
                     earners and fastest-growing dues in the window.

All money is integer paise internally; every money field name is registered in
``payout.money.MONEY_KEYS`` so the egress middleware converts it to rupees.
Grouping into ISO weeks happens in Python so both backends behave identically.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException

from payout.api.auth import get_current_user
from payout.db import get_connection

router = APIRouter()

_RECOVERY_EVENTS = ("RENT_RECOVERED", "XC_RENT_RECOVERED")


def _split_companies(s: str | None) -> list[str]:
    if not s:
        return []
    return [c.strip() for c in s.split(",") if c.strip()]


def _iso_week(day: str) -> str:
    y, w, _ = date.fromisoformat(day[:10]).isocalendar()
    return f"{y}-W{w:02d}"


def _week_monday(bucket: str) -> str:
    """'2026-W23' -> ISO date of that week's Monday (for chart axes)."""
    y, w = bucket.split("-W")
    return date.fromisocalendar(int(y), int(w), 1).isoformat()


def _last_weeks(n: int) -> list[str]:
    """The last ``n`` ISO week buckets, oldest first, ending this week."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    out = []
    for i in range(n - 1, -1, -1):
        d = monday - timedelta(weeks=i)
        y, w, _ = d.isocalendar()
        out.append(f"{y}-W{w:02d}")
    return out


def _weeks_param(weeks: int) -> int:
    if not 1 <= weeks <= 53:
        raise HTTPException(400, "weeks must be between 1 and 53")
    return weeks


def _co_clause(cos: list[str], column: str) -> tuple[str, list]:
    if not cos:
        return "", []
    ph = ",".join("?" for _ in cos)
    return f" AND {column} IN ({ph})", list(cos)


def _window(date_from: str | None, date_to: str | None, default_days: int = 28):
    today = date.today()
    try:
        d_to = date.fromisoformat(date_to) if date_to else today
        d_from = (
            date.fromisoformat(date_from) if date_from else d_to - timedelta(days=default_days - 1)
        )
    except ValueError:
        raise HTTPException(400, "date_from / date_to must be ISO dates")  # noqa: B904
    if d_from > d_to:
        raise HTTPException(400, "date_from must be on or before date_to")
    return d_from.isoformat(), d_to.isoformat()


# ─────────────────────────────── /trends ────────────────────────────────────


@router.get("/trends")
def money_trends(
    companies: str | None = None,
    weeks: int = 12,
    _: dict = Depends(get_current_user),
) -> dict:
    """Weekly money-flow series over the last ``weeks`` ISO weeks.

    Sourced from the transactions ledger grouped by the week of ``cycle_end``
    (what the money was *for*, not when the row was written), so a late-
    processed file lands in the week it belongs to.
    """
    weeks = _weeks_param(weeks)
    cos = _split_companies(companies)
    buckets = _last_weeks(weeks)
    since_monday = _week_monday(buckets[0])

    co_sql, co_params = _co_clause(cos, "t.company")
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT t.cycle_end, t.event_type, t.amount, t.company "
            f"FROM transactions t "
            f"WHERE t.cycle_end >= ? "
            f"  AND t.event_type IN ('PAYOUT','RELEASE','RENT','RENT_COLLECTED',"
            f"      'RENT_MISSED','RENT_RECOVERED','XC_RENT_RECOVERED','DUES_CARRY') "
            f"{co_sql}",
            [since_monday] + co_params,
        ).fetchall()

    zero = lambda: {  # noqa: E731
        "gross_payout": 0,
        "released": 0,
        "rent_charged": 0,
        "rent_collected": 0,
        "rent_missed": 0,
        "arrears_recovered": 0,
        "dues_delta": 0,
    }
    per_week: dict[str, dict] = {b: zero() for b in buckets}
    for r in rows:
        wk = _iso_week(r["cycle_end"])
        if wk not in per_week:
            continue
        d = per_week[wk]
        et, amt = r["event_type"], int(r["amount"] or 0)
        if et == "PAYOUT":
            d["gross_payout"] += amt
        elif et == "RELEASE":
            d["released"] += -amt
        elif et == "RENT":
            d["rent_charged"] += -amt
        elif et == "RENT_COLLECTED":
            d["rent_collected"] += amt
        elif et == "RENT_MISSED":
            d["rent_missed"] += -amt
        elif et in _RECOVERY_EVENTS:
            d["arrears_recovered"] += amt
        elif et == "DUES_CARRY":
            # negative amount = dues grew that week; positive = paid down.
            d["dues_delta"] += amt
    return {
        "weeks": [{"week": b, "week_start": _week_monday(b), **per_week[b]} for b in buckets],
    }


# ───────────────────────────── /collection ──────────────────────────────────

_AGING_BUCKETS = (
    ("0-14d", 0, 14),
    ("15-28d", 15, 28),
    ("29-60d", 29, 60),
    ("60d+", 61, 100_000),
)


@router.get("/collection")
def collection_efficiency(
    companies: str | None = None,
    weeks: int = 12,
    _: dict = Depends(get_current_user),
) -> dict:
    """Rent collection efficiency + arrears aging + COD exposure.

    Day-level truth from ``ev_daily_ledger``: every billable EV-day is either
    collected (billed/recovered), missed (fell to arrears and not yet healed)
    or pending (no cycle has processed it yet).
    """
    weeks = _weeks_param(weeks)
    cos = _split_companies(companies)
    buckets = _last_weeks(weeks)
    since = _week_monday(buckets[0])
    today = date.today()

    led_co = ""
    led_params: list = []
    if cos:
        ph = ",".join("?" for _ in cos)
        led_co = (
            f" AND l.assigned_person_id IN (SELECT rm.person_id FROM rider_master rm "
            f" WHERE rm.company IN ({ph}) AND rm.is_active=1)"
        )
        led_params = list(cos)

    with get_connection() as conn:
        day_rows = conn.execute(
            f"SELECT l.day, "
            f"  SUM(CASE WHEN l.state='billable' THEN l.daily_cost ELSE 0 END) AS expected, "
            f"  SUM(CASE WHEN l.billing_status IN ('billed','recovered') "
            f"      THEN l.daily_cost ELSE 0 END) AS collected, "
            f"  SUM(CASE WHEN l.billing_status='missed' THEN l.daily_cost ELSE 0 END) AS missed, "
            f"  SUM(CASE WHEN l.billing_status='pending' "
            f"       OR (l.billing_status IS NULL AND l.state='billable') "
            f"      THEN l.daily_cost ELSE 0 END) AS pending "
            f"FROM ev_daily_ledger l WHERE l.day >= ? {led_co} GROUP BY l.day",
            [since] + led_params,
        ).fetchall()

        per_week = {b: {"expected": 0, "collected": 0, "missed": 0, "pending": 0} for b in buckets}
        for r in day_rows:
            wk = _iso_week(r["day"])
            if wk in per_week:
                for k in ("expected", "collected", "missed", "pending"):
                    per_week[wk][k] += int(r[k] or 0)
        series = []
        for b in buckets:
            d = per_week[b]
            rate = (d["collected"] / d["expected"] * 100) if d["expected"] else None
            series.append(
                {
                    "week": b,
                    "week_start": _week_monday(b),
                    **d,
                    "collection_rate": round(rate, 1) if rate is not None else None,
                }
            )

        # Arrears aging: age of each debtor's OLDEST still-missed day.
        # ACTIVE EV holders only — riders who returned their EV are dormant
        # (debt kept silently, payouts held); they are chased differently and
        # would only inflate the chase-list here.
        aging_rows = conn.execute(
            "SELECT ea.person_id, ea.outstanding, "
            "       (SELECT MIN(l.day) FROM ev_daily_ledger l "
            "        WHERE l.assigned_person_id = ea.person_id "
            "          AND l.billing_status='missed') AS oldest_missed_day "
            "FROM ev_arrears ea WHERE ea.outstanding > 0 "
            "  AND EXISTS (SELECT 1 FROM ev_assignments a "
            "              WHERE a.person_id = ea.person_id AND a.returned_date IS NULL)"
        ).fetchall()
        aging = [
            {"bucket": name, "riders": 0, "outstanding": 0} for name, _lo, _hi in _AGING_BUCKETS
        ]
        for r in aging_rows:
            oldest = r["oldest_missed_day"]
            age = (today - date.fromisoformat(str(oldest)[:10])).days if oldest else 0
            for i, (_name, lo, hi) in enumerate(_AGING_BUCKETS):
                if lo <= age <= hi:
                    aging[i]["riders"] += 1
                    aging[i]["outstanding"] += int(r["outstanding"] or 0)
                    break

        # Recovery velocity: last 4 full-ish weeks of missed vs recovered.
        four_weeks_ago = (today - timedelta(days=27)).isoformat()
        vel = conn.execute(
            "SELECT "
            "  SUM(CASE WHEN event_type='RENT_MISSED' THEN -amount ELSE 0 END) AS missed, "
            "  SUM(CASE WHEN event_type IN ('RENT_RECOVERED','XC_RENT_RECOVERED') "
            "      THEN amount ELSE 0 END) AS recovered "
            "FROM transactions t WHERE date(t.created_at) >= ?",
            [four_weeks_ago],
        ).fetchone()

        # COD exposure: everything not yet marked cleared.
        cod_co, cod_params = _co_clause(cos, "ch.company")
        cod = conn.execute(
            f"SELECT COALESCE(SUM(ch.amount),0) AS total_pending, "
            f"       COUNT(DISTINCT ch.person_id) AS riders, "
            f"       MIN(ch.created_at) AS oldest "
            f"FROM cod_holds ch WHERE ch.cleared_at IS NULL {cod_co}",
            cod_params,
        ).fetchone()

    return {
        "weekly": series,
        "aging": aging,
        "velocity_4w": {
            "missed": int(vel["missed"] or 0),
            "recovered": int(vel["recovered"] or 0),
        },
        "cod_exposure": {
            "total_pending": int(cod["total_pending"] or 0),
            "riders": int(cod["riders"] or 0),
            "oldest": str(cod["oldest"])[:10] if cod["oldest"] else None,
        },
    }


# ──────────────────────────────── /fleet ────────────────────────────────────


@router.get("/fleet")
def fleet_economics(
    date_from: str | None = None,
    date_to: str | None = None,
    _: dict = Depends(get_current_user),
) -> dict:
    """Per-EV and per-provider P&L over a date window (default: last 28 days).

    From the daily ledger: what each EV *earned* (billed + recovered days)
    versus what the provider charges for every day the EV exists. Margin is
    earned − provider cost; utilization is billable days ÷ ledger days.
    """
    d_from, d_to = _window(date_from, date_to)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT l.ev_id, m.provider, m.model_name AS model, "
            "  COUNT(*) AS ledger_days, "
            "  SUM(CASE WHEN l.state='billable' THEN 1 ELSE 0 END) AS billable_days, "
            "  SUM(CASE WHEN l.billing_status='missed' THEN 1 ELSE 0 END) AS missed_days, "
            "  SUM(CASE WHEN l.state='maintenance' THEN 1 ELSE 0 END) AS maintenance_days, "
            "  SUM(CASE WHEN l.state='unassigned' THEN 1 ELSE 0 END) AS idle_days, "
            "  SUM(CASE WHEN l.billing_status IN ('billed','recovered') "
            "      THEN l.daily_cost ELSE 0 END) AS earned, "
            "  SUM(CASE WHEN l.billing_status='missed' THEN l.daily_cost ELSE 0 END) AS missed, "
            "  SUM(l.provider_cost) AS provider_owed "
            "FROM ev_daily_ledger l "
            "JOIN ev_units  u ON u.ev_id = l.ev_id "
            "JOIN ev_models m ON m.model_id = u.model_id "
            "WHERE l.day BETWEEN ? AND ? "
            "GROUP BY l.ev_id, m.provider, m.model_name",
            [d_from, d_to],
        ).fetchall()
        holders = {
            r["ev_id"]: (r["person_id"], r["display_name"])
            for r in conn.execute(
                "SELECT a.ev_id, a.person_id, pr.display_name "
                "FROM ev_assignments a JOIN person_registry pr ON pr.person_id=a.person_id "
                "WHERE a.returned_date IS NULL"
            ).fetchall()
        }

    evs = []
    providers: dict[str, dict] = defaultdict(
        lambda: {"evs": 0, "earned": 0, "missed": 0, "provider_owed": 0, "margin": 0}
    )
    for r in rows:
        earned = int(r["earned"] or 0)
        owed = int(r["provider_owed"] or 0)
        margin = earned - owed
        pid, holder = holders.get(r["ev_id"], (None, None))
        ledger_days = int(r["ledger_days"] or 0)
        billable = int(r["billable_days"] or 0)
        evs.append(
            {
                "ev_id": r["ev_id"],
                "provider": r["provider"],
                "model": r["model"],
                "holder_person_id": pid,
                "holder": holder,
                "ledger_days": ledger_days,
                "billable_days": billable,
                "missed_days": int(r["missed_days"] or 0),
                "maintenance_days": int(r["maintenance_days"] or 0),
                "idle_days": int(r["idle_days"] or 0),
                "utilization": round(billable / ledger_days * 100, 1) if ledger_days else 0.0,
                "earned": earned,
                "missed": int(r["missed"] or 0),
                "provider_owed": owed,
                "margin": margin,
            }
        )
        p = providers[r["provider"]]
        p["evs"] += 1
        p["earned"] += earned
        p["missed"] += int(r["missed"] or 0)
        p["provider_owed"] += owed
        p["margin"] += margin
    evs.sort(key=lambda e: e["margin"])  # worst first — the ones losing money
    return {
        "date_from": d_from,
        "date_to": d_to,
        "providers": [{"provider": name, **vals} for name, vals in sorted(providers.items())],
        "evs": evs,
    }


# ──────────────────────────────── /riders ───────────────────────────────────


@router.get("/riders")
def rider_analytics(
    companies: str | None = None,
    weeks: int = 12,
    _: dict = Depends(get_current_user),
) -> dict:
    """Rider movement per week + top earners and growing dues in the window.

    ``paid``    — distinct persons with a PAYOUT that week.
    ``new``     — persons whose first-ever PAYOUT (any company) fell that week.
    ``churned`` — persons paid in the previous 4 weeks but not that week.
    """
    weeks = _weeks_param(weeks)
    cos = _split_companies(companies)
    buckets = _last_weeks(weeks)
    since = _week_monday(buckets[0])
    co_sql, co_params = _co_clause(cos, "t.company")

    with get_connection() as conn:
        pay_rows = conn.execute(
            f"SELECT DISTINCT t.person_id, t.cycle_end FROM transactions t "
            f"WHERE t.event_type='PAYOUT' AND t.cycle_end >= ? {co_sql}",
            [since] + co_params,
        ).fetchall()
        firsts = {
            r["person_id"]: r["first_end"]
            for r in conn.execute(
                "SELECT person_id, MIN(cycle_end) AS first_end FROM transactions "
                "WHERE event_type='PAYOUT' GROUP BY person_id"
            ).fetchall()
        }
        # look-back for churn: who was paid in the 4 weeks before the window
        lookback = (date.fromisoformat(since) - timedelta(weeks=4)).isoformat()
        prior_rows = conn.execute(
            f"SELECT DISTINCT t.person_id, t.cycle_end FROM transactions t "
            f"WHERE t.event_type='PAYOUT' AND t.cycle_end >= ? AND t.cycle_end < ? {co_sql}",
            [lookback, since] + co_params,
        ).fetchall()

        top_earners = [
            dict(r)
            for r in conn.execute(
                f"SELECT t.person_id, pr.display_name, SUM(-t.amount) AS released, "
                f"       COUNT(DISTINCT t.cycle_end) AS cycles "
                f"FROM transactions t JOIN person_registry pr ON pr.person_id=t.person_id "
                f"WHERE t.event_type='RELEASE' AND t.cycle_end >= ? {co_sql} "
                f"GROUP BY t.person_id, pr.display_name ORDER BY released DESC LIMIT 10",
                [since] + co_params,
            ).fetchall()
        ]
        sliding = [
            dict(r)
            for r in conn.execute(
                f"SELECT t.person_id, pr.display_name, SUM(-t.amount) AS dues_delta, "
                f"       COALESCE((SELECT -b.current_balance FROM balances b "
                f"                 WHERE b.person_id=t.person_id AND b.current_balance<0), 0) "
                f"         AS dues "
                f"FROM transactions t JOIN person_registry pr ON pr.person_id=t.person_id "
                f"WHERE t.event_type='DUES_CARRY' AND t.amount < 0 AND t.cycle_end >= ? {co_sql} "
                f"GROUP BY t.person_id, pr.display_name ORDER BY dues_delta DESC LIMIT 10",
                [since] + co_params,
            ).fetchall()
        ]

    paid_by_week: dict[str, set] = defaultdict(set)
    for r in pay_rows:
        paid_by_week[_iso_week(r["cycle_end"])].add(r["person_id"])
    prior_paid_weeks: dict[str, set] = defaultdict(set)
    for r in prior_rows:
        prior_paid_weeks[_iso_week(r["cycle_end"])].add(r["person_id"])

    def _recent(idx: int) -> set:
        """Persons paid in the 4 weeks before buckets[idx]."""
        out: set = set()
        y, w = buckets[idx].split("-W")
        monday = date.fromisocalendar(int(y), int(w), 1)
        for back in range(1, 5):
            d = monday - timedelta(weeks=back)
            yy, ww, _ = d.isocalendar()
            key = f"{yy}-W{ww:02d}"
            out |= paid_by_week.get(key, set()) | prior_paid_weeks.get(key, set())
        return out

    series = []
    first_week = {pid: _iso_week(end) for pid, end in firsts.items()}
    for i, b in enumerate(buckets):
        paid = paid_by_week.get(b, set())
        new = {p for p in paid if first_week.get(p) == b}
        churned = _recent(i) - paid
        series.append(
            {
                "week": b,
                "week_start": _week_monday(b),
                "paid": len(paid),
                "new": len(new),
                "churned": len(churned),
            }
        )
    return {"weekly": series, "top_earners": top_earners, "sliding_into_dues": sliding}


# ─────────────────────────── the money story ─────────────────────────────
#
# Everything below feeds the numbers-first dashboard: one windowed "story"
# of how money flowed (in → withheld → out; rent charged → collected /
# missed → later recovered / written off / still owed) plus the same story
# grouped by company, rider, or EV. Written for a reader who is not an
# accountant: every figure is one SQL aggregate with a plain meaning.

_TXN_WINDOW = "date(t.created_at) BETWEEN ? AND ?"
# Correction rows (heal refunds, write-offs, credit offsets) are written with
# company='' — attribute them to the person's deduction company so company
# filters and groupings still see them.
_CO_EXPR = "COALESCE(NULLIF(t.company, ''), pr.deduction_company, '?')"


def _flow_sums(conn, wf: str, wt: str, cos: list[str]) -> dict:
    co_sql, co_args = _co_clause(cos, _CO_EXPR)
    row = conn.execute(
        "SELECT "
        " SUM(CASE WHEN t.event_type='PAYOUT' THEN t.amount ELSE 0 END) AS gross_payout, "
        " SUM(CASE WHEN t.event_type='RELEASE' THEN -t.amount ELSE 0 END) AS released, "
        " SUM(CASE WHEN t.event_type='RENT' THEN -t.amount ELSE 0 END) AS rent_charged, "
        " SUM(CASE WHEN t.event_type='RENT_COLLECTED' THEN t.amount ELSE 0 END) AS rent_collected, "
        " SUM(CASE WHEN t.event_type='RENT_MISSED' THEN -t.amount ELSE 0 END) AS rent_missed, "
        " SUM(CASE WHEN t.event_type IN ('RENT_RECOVERED','XC_RENT_RECOVERED') "
        "     THEN t.amount ELSE 0 END) AS arrears_recovered, "
        " SUM(CASE WHEN t.event_type='RENT_REVERSAL' THEN t.amount ELSE 0 END) AS written_off, "
        " SUM(CASE WHEN t.event_type='DEPOSIT_APPLIED' THEN t.amount ELSE 0 END) "
        "   AS deposit_applied, "
        " SUM(CASE WHEN t.event_type='ADJUSTMENT' "
        "      AND t.remarks LIKE 'Credit balance applied%' THEN -t.amount ELSE 0 END) "
        "   AS credit_offset, "
        " SUM(CASE WHEN t.event_type='ADJUSTMENT' "
        "      AND t.remarks LIKE 'Refund — EV%' THEN t.amount ELSE 0 END) AS refunded "
        "FROM transactions t "
        "JOIN person_registry pr ON pr.person_id = t.person_id "
        f"WHERE {_TXN_WINDOW}{co_sql}",
        [wf, wt, *co_args],
    ).fetchone()
    out = {k: int(row[k] or 0) for k in row.keys()}  # noqa: SIM118 (sqlite3.Row)
    cod_co_sql, cod_co_args = _co_clause(cos, "company")
    out["cod_held"] = int(
        conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM cod_holds "
            f"WHERE date(created_at) BETWEEN ? AND ?{cod_co_sql}",
            [wf, wt, *cod_co_args],
        ).fetchone()[0]
    )
    return out


@router.get("/story")
def money_story(
    companies: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    _: dict = Depends(get_current_user),
) -> dict:
    """The window's money flow in plain terms, plus today's debt position.

    ``flow`` is scoped to the window (by when rows were written, matching
    /summary); ``position`` is live — where the debt stands right now,
    including the dormant split (EV returned, debt kept silently).
    """
    wf, wt = _window(date_from, date_to)
    days = (date.fromisoformat(wt) - date.fromisoformat(wf)).days + 1
    cos = _split_companies(companies)
    with get_connection() as conn:
        flow = _flow_sums(conn, wf, wt, cos)
        pos = conn.execute(
            "SELECT "
            " COALESCE(SUM(CASE WHEN ea.outstanding > 0 THEN ea.outstanding END), 0) "
            "   AS ev_arrears, "
            " COALESCE(SUM(CASE WHEN ea.outstanding > 0 AND a.person_id IS NOT NULL "
            "     THEN ea.outstanding END), 0) AS ev_arrears_active, "
            " COALESCE(SUM(CASE WHEN ea.outstanding > 0 AND a.person_id IS NULL "
            "     THEN ea.outstanding END), 0) AS ev_arrears_dormant "
            "FROM ev_arrears ea "
            "LEFT JOIN (SELECT DISTINCT person_id FROM ev_assignments "
            "           WHERE returned_date IS NULL) a ON a.person_id = ea.person_id"
        ).fetchone()
        # Dues split mirrors the EV-arrears split: an ex-EV holder (no open
        # assignment, has a closed one) with a negative balance is dormant —
        # their debt often rolled into dues instead of the EV-arrears bucket.
        bal = conn.execute(
            "SELECT "
            " COALESCE(SUM(CASE WHEN b.current_balance < 0 THEN -b.current_balance END), 0) "
            "   AS dues, "
            " COALESCE(SUM(CASE WHEN b.current_balance < 0 AND o.person_id IS NULL "
            "     AND r.person_id IS NOT NULL THEN -b.current_balance END), 0) AS dues_dormant, "
            " COALESCE(SUM(CASE WHEN b.current_balance > 0 THEN b.current_balance END), 0) "
            "   AS credit "
            "FROM balances b "
            "LEFT JOIN (SELECT DISTINCT person_id FROM ev_assignments "
            "           WHERE returned_date IS NULL) o ON o.person_id = b.person_id "
            "LEFT JOIN (SELECT DISTINCT person_id FROM ev_assignments "
            "           WHERE returned_date IS NOT NULL) r ON r.person_id = b.person_id"
        ).fetchone()
        # Dormant riders = ex-EV holders, no open EV, owing in EITHER bucket.
        dormant_riders = conn.execute(
            "SELECT COUNT(*) FROM person_registry pr "
            "LEFT JOIN ev_arrears ea ON ea.person_id = pr.person_id "
            "LEFT JOIN balances   b  ON b.person_id  = pr.person_id "
            "WHERE NOT EXISTS (SELECT 1 FROM ev_assignments a "
            "                  WHERE a.person_id = pr.person_id "
            "                    AND a.returned_date IS NULL) "
            "  AND (COALESCE(ea.outstanding, 0) > 0 "
            "       OR (COALESCE(b.current_balance, 0) < 0 "
            "           AND EXISTS (SELECT 1 FROM ev_assignments a "
            "                       WHERE a.person_id = pr.person_id "
            "                         AND a.returned_date IS NOT NULL)))"
        ).fetchone()[0]
        cod = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM cod_holds WHERE cleared_at IS NULL"
        ).fetchone()[0]
    return {
        "window": {"from": wf, "to": wt, "days": days},
        "flow": flow,
        "position": {
            "ev_arrears": pos["ev_arrears"],
            "ev_arrears_active": pos["ev_arrears_active"],
            "ev_arrears_dormant": pos["ev_arrears_dormant"],
            "dormant_riders": dormant_riders,
            "dues": bal["dues"],
            "dues_dormant": bal["dues_dormant"],
            "credit": bal["credit"],
            "cod_uncleared": int(cod),
        },
    }


@router.get("/story/by")
def money_story_by(
    dim: str,
    companies: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 300,
    _: dict = Depends(get_current_user),
) -> dict:
    """The same story grouped by ``dim``: 'company', 'rider', or 'ev'.

    company/rider come from the transactions trail (corrections attributed
    via the person's deduction company). 'ev' comes from the day-ledger —
    per-EV charged/collected/missed for the window, provider cost, margin —
    with write-offs attributed from RENT_REVERSAL remarks (the heal writes
    'EV <id> returned' machine-formatted).
    """
    wf, wt = _window(date_from, date_to)
    days = (date.fromisoformat(wt) - date.fromisoformat(wf)).days + 1
    cos = _split_companies(companies)
    limit = max(1, min(int(limit), 1000))
    with get_connection() as conn:
        if dim == "company":
            co_sql, co_args = _co_clause(cos, _CO_EXPR)
            rows = conn.execute(
                f"SELECT {_CO_EXPR} AS company, "
                " SUM(CASE WHEN t.event_type='PAYOUT' THEN t.amount ELSE 0 END) AS gross_payout, "
                " SUM(CASE WHEN t.event_type='RELEASE' THEN -t.amount ELSE 0 END) AS released, "
                " SUM(CASE WHEN t.event_type='RENT' THEN -t.amount ELSE 0 END) AS rent_charged, "
                " SUM(CASE WHEN t.event_type='RENT_COLLECTED' THEN t.amount ELSE 0 END) "
                "   AS rent_collected, "
                " SUM(CASE WHEN t.event_type='RENT_MISSED' THEN -t.amount ELSE 0 END) "
                "   AS rent_missed, "
                " SUM(CASE WHEN t.event_type IN ('RENT_RECOVERED','XC_RENT_RECOVERED') "
                "     THEN t.amount ELSE 0 END) AS arrears_recovered, "
                " SUM(CASE WHEN t.event_type='RENT_REVERSAL' THEN t.amount ELSE 0 END) "
                "   AS written_off, "
                " SUM(CASE WHEN t.event_type='DEPOSIT_APPLIED' THEN t.amount ELSE 0 END) "
                "   AS deposit_applied, "
                " COUNT(DISTINCT CASE WHEN t.event_type='PAYOUT' THEN t.person_id END) AS riders "
                "FROM transactions t "
                "JOIN person_registry pr ON pr.person_id = t.person_id "
                f"WHERE {_TXN_WINDOW}{co_sql} "
                f"GROUP BY {_CO_EXPR} ORDER BY rent_charged DESC",
                [wf, wt, *co_args],
            ).fetchall()
            out = [dict(r) for r in rows if r["company"]]
            # live outstanding per company (person's deduction company)
            live = {
                r["co"]: (int(r["out"] or 0), int(r["dues"] or 0))
                for r in conn.execute(
                    "SELECT pr.deduction_company AS co, "
                    "  SUM(COALESCE(ea.outstanding, 0)) AS out, "
                    "  SUM(CASE WHEN COALESCE(b.current_balance,0) < 0 "
                    "      THEN -b.current_balance ELSE 0 END) AS dues "
                    "FROM person_registry pr "
                    "LEFT JOIN ev_arrears ea ON ea.person_id = pr.person_id "
                    "LEFT JOIN balances b ON b.person_id = pr.person_id "
                    "GROUP BY pr.deduction_company"
                )
            }
            for r in out:
                o = live.get(r["company"], (0, 0))
                r["outstanding"] = o[0]
                r["dues"] = o[1]
            return {"window": {"from": wf, "to": wt, "days": days}, "dim": dim, "rows": out}

        if dim == "rider":
            co_sql, co_args = _co_clause(cos, _CO_EXPR)
            rows = conn.execute(
                "SELECT t.person_id, pr.display_name, "
                f" MAX({_CO_EXPR}) AS company, "
                " SUM(CASE WHEN t.event_type='PAYOUT' THEN t.amount ELSE 0 END) AS gross_payout, "
                " SUM(CASE WHEN t.event_type='RELEASE' THEN -t.amount ELSE 0 END) AS released, "
                " SUM(CASE WHEN t.event_type='RENT' THEN -t.amount ELSE 0 END) AS rent_charged, "
                " SUM(CASE WHEN t.event_type='RENT_COLLECTED' THEN t.amount ELSE 0 END) "
                "   AS rent_collected, "
                " SUM(CASE WHEN t.event_type='RENT_MISSED' THEN -t.amount ELSE 0 END) "
                "   AS rent_missed, "
                " SUM(CASE WHEN t.event_type IN ('RENT_RECOVERED','XC_RENT_RECOVERED') "
                "     THEN t.amount ELSE 0 END) AS arrears_recovered, "
                " SUM(CASE WHEN t.event_type='RENT_REVERSAL' THEN t.amount ELSE 0 END) "
                "   AS written_off, "
                " SUM(CASE WHEN t.event_type='DEPOSIT_APPLIED' THEN t.amount ELSE 0 END) "
                "   AS deposit_applied, "
                " COALESCE(MAX(ea.outstanding), 0) AS outstanding, "
                " COALESCE(MAX(b.current_balance), 0) AS balance "
                "FROM transactions t "
                "JOIN person_registry pr ON pr.person_id = t.person_id "
                "LEFT JOIN ev_arrears ea ON ea.person_id = t.person_id "
                "LEFT JOIN balances b ON b.person_id = t.person_id "
                f"WHERE {_TXN_WINDOW}{co_sql} "
                "GROUP BY t.person_id, pr.display_name "
                "ORDER BY 6 DESC LIMIT ?",  # 6 = rent_charged (PG: no aliases in ORDER BY exprs)
                [wf, wt, *co_args, limit],
            ).fetchall()
            return {
                "window": {"from": wf, "to": wt, "days": days},
                "dim": dim,
                "rows": [dict(r) for r in rows],
            }

        if dim == "ev":
            rows = conn.execute(
                "SELECT l.ev_id, m.provider, m.model_name AS model, u.status, "
                " SUM(CASE WHEN l.billing_status IN ('billed','missed','recovered') "
                "     THEN l.daily_cost ELSE 0 END) AS charged, "
                " SUM(CASE WHEN l.billing_status IN ('billed','recovered') "
                "     THEN l.daily_cost ELSE 0 END) AS collected, "
                " SUM(CASE WHEN l.billing_status='missed' THEN l.daily_cost ELSE 0 END) "
                "   AS missed, "
                " SUM(l.provider_cost) AS provider_cost, "
                " COUNT(*) AS ledger_days, "
                " MAX(CASE WHEN a.person_id IS NOT NULL THEN pr.display_name END) AS holder, "
                " MAX(a.person_id) AS holder_person_id "
                "FROM ev_daily_ledger l "
                "JOIN ev_units u ON u.ev_id = l.ev_id "
                "JOIN ev_models m ON m.model_id = u.model_id "
                "LEFT JOIN ev_assignments a "
                "  ON a.ev_id = l.ev_id AND a.returned_date IS NULL "
                "LEFT JOIN person_registry pr ON pr.person_id = a.person_id "
                "WHERE l.day BETWEEN ? AND ? "
                "GROUP BY l.ev_id, m.provider, m.model_name, u.status "
                "ORDER BY charged DESC LIMIT ?",
                [wf, wt, limit],
            ).fetchall()
            out = [dict(r) for r in rows]
            # Write-offs per EV, from the heal's machine-formatted remarks.
            wo: dict[str, int] = {}
            for r in conn.execute(
                "SELECT t.amount, t.remarks FROM transactions t "
                "WHERE t.event_type='RENT_REVERSAL' AND date(t.created_at) BETWEEN ? AND ?",
                [wf, wt],
            ):
                m = re.search(r"EV (\S+) returned", r["remarks"] or "")
                if m:
                    wo[m.group(1)] = wo.get(m.group(1), 0) + int(r["amount"])
            known = {r["ev_id"] for r in out}
            for r in out:
                r["written_off"] = wo.get(r["ev_id"], 0)
                r["margin"] = int(r["collected"] or 0) - int(r["provider_cost"] or 0)
            # An EV healed out of the ledger entirely still deserves a row.
            for ev_id, amount in wo.items():
                if ev_id not in known:
                    out.append(
                        {
                            "ev_id": ev_id,
                            "provider": None,
                            "model": None,
                            "status": "returned",
                            "charged": 0,
                            "collected": 0,
                            "missed": 0,
                            "provider_cost": 0,
                            "ledger_days": 0,
                            "holder": None,
                            "holder_person_id": None,
                            "written_off": amount,
                            "margin": 0,
                        }
                    )
            return {"window": {"from": wf, "to": wt, "days": days}, "dim": dim, "rows": out}

    raise HTTPException(400, "dim must be 'company', 'rider', or 'ev'")
