"""Per-rider provider reconciliation — the weekly 'expected vs collected' view.

Aggregates ``ev_daily_ledger`` for one provider (Raft, Blive, …) over a date
range, grouped by the rider holding the EV. Answers the question an operator
has to take to their boss every week: for each rider, how much EV rent were we
*expected* to collect, how much did we *actually* collect, how much slipped to
arrears, and — when a rider's days were billed through a company payout — which
company actually settled it (the "settled elsewhere" signal).

Anchor the date range to the provider's bill period (what they charged) so the
report ties back to a document, not a guessed calendar week. The ledger is the
day-level bridge: provider_cost is what we owe the provider; daily_cost is the
rider-side expectation; billing_status records the outcome per day.
"""

from __future__ import annotations

import sqlite3


def _norm_provider(p: str) -> str:
    return (p or "").strip().title()


def provider_rider_reconciliation(
    conn: sqlite3.Connection, provider: str, date_from: str, date_to: str
) -> dict:
    """Return per-rider reconciliation rows + totals for ``provider`` between
    ``date_from`` and ``date_to`` (inclusive ISO dates).

    Each row: person_id, name, ev_ids, expected, collected, missed (still
    outstanding), recovered, pending, collection_pct, settled_via (companies
    whose payout actually collected the rent).
    """
    prov = _norm_provider(provider)
    rows = conn.execute(
        """
        SELECT l.assigned_person_id                       AS person_id,
               COALESCE(pr.display_name, '(unknown)')     AS name,
               GROUP_CONCAT(DISTINCT l.ev_id)             AS ev_ids,
               COALESCE(SUM(l.daily_cost), 0)             AS expected,
               COALESCE(SUM(CASE WHEN l.billing_status IN ('billed','recovered')
                                 THEN l.daily_cost ELSE 0 END), 0) AS collected,
               COALESCE(SUM(CASE WHEN l.billing_status='missed'
                                 THEN l.daily_cost ELSE 0 END), 0) AS missed,
               COALESCE(SUM(CASE WHEN l.billing_status='recovered'
                                 THEN l.daily_cost ELSE 0 END), 0) AS recovered,
               COALESCE(SUM(CASE WHEN l.billing_status='pending'
                                      OR (l.billing_status IS NULL AND l.state='billable')
                                 THEN l.daily_cost ELSE 0 END), 0) AS pending,
               GROUP_CONCAT(DISTINCT t.company)           AS settled_via
        FROM ev_daily_ledger l
        JOIN ev_units  u ON u.ev_id = l.ev_id
        JOIN ev_models m ON m.model_id = u.model_id
        LEFT JOIN person_registry pr ON pr.person_id = l.assigned_person_id
        LEFT JOIN transactions t
               ON t.id = l.cycle_event_id AND t.event_type = 'RENT'
        WHERE LOWER(m.provider) = LOWER(?)
          AND l.day BETWEEN ? AND ?
          AND l.assigned_person_id IS NOT NULL
          AND l.state = 'billable'
        GROUP BY l.assigned_person_id, name
        ORDER BY missed DESC, expected DESC
        """,
        (prov, date_from, date_to),
    ).fetchall()

    out_rows: list[dict] = []
    for r in rows:
        expected = round(float(r["expected"] or 0), 2)
        collected = round(float(r["collected"] or 0), 2)
        missed = round(float(r["missed"] or 0), 2)
        out_rows.append({
            "person_id": r["person_id"],
            "name": r["name"],
            "ev_ids": r["ev_ids"] or "",
            "expected": expected,
            "collected": collected,
            "missed": missed,                       # still outstanding for the window
            "recovered": round(float(r["recovered"] or 0), 2),
            "pending": round(float(r["pending"] or 0), 2),
            "collection_pct": round(100.0 * collected / expected, 1) if expected else 0.0,
            "settled_via": r["settled_via"] or "",
        })

    def s(key: str) -> float:
        return round(sum(x[key] for x in out_rows), 2)

    exp_t, col_t = s("expected"), s("collected")
    totals = {
        "expected": exp_t,
        "collected": col_t,
        "missed": s("missed"),
        "recovered": s("recovered"),
        "pending": s("pending"),
        "collection_pct": round(100.0 * col_t / exp_t, 1) if exp_t else 0.0,
        "rider_count": len(out_rows),
    }
    return {"provider": prov, "from": date_from, "to": date_to,
            "rows": out_rows, "totals": totals}
