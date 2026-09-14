"""Per-rider EV rent collection over a period, out of ``ev_daily_ledger``.

For each rider holding one of a provider's vehicles: how much rent we could
have billed them, how much we got, how much slipped to arrears, and — when
their days were settled through a company payout — which company settled it.

**This is a collection rate, not a reconciliation**, and the distinction cost
real money before it was drawn. Nothing external enters the calculation:
``expected`` is our own day ledger's opinion of what a rider owed, so a
provider over-billing us cannot appear here, and neither can a vehicle they
charged for that our books say we gave back. Reconciling against the
provider's own document is ``domain/provider_bill.py``, hung off an uploaded
bill. Two things called reconciliation on one page taught the office to trust
neither.

Three deliberate repairs, 2026-09-14, after the week-36 bill was reconciled by
hand and this view turned out to have been silent about most of what it found:

* **``provider_owed`` is now in the rows.** ``daily_cost`` is what we could
  bill a rider; ``provider_cost`` is what the vehicle costs us whatever
  happens. Only the first was here, so the number that decides whether a unit
  pays for itself was missing from the report about whether units pay for
  themselves.
* **Days nobody held are reported instead of dropped.** The old query filtered
  ``assigned_person_id IS NOT NULL``, so a unit sitting on our books unassigned
  produced no row at all. In week 36 that was the single largest class of
  disputed money, and this table could not show a rupee of it.
* **``recovery_pct`` divides by what we owed**, alongside the original
  ``collection_pct``. The old percentage's denominator is already net of
  non-billable days, so a rider whose EV spent four days in the workshop read
  100% collected while the vehicle lost money all week. Both numbers are true;
  they answer different questions, and only one of them was here.
"""

from __future__ import annotations

import sqlite3


def _norm_provider(p: str) -> str:
    return (p or "").strip().title()


def provider_rider_reconciliation(
    conn: sqlite3.Connection, provider: str, date_from: str, date_to: str
) -> dict:
    """Per-rider rows + totals for ``provider`` between ``date_from`` and
    ``date_to`` (inclusive ISO dates).

    Each row: person_id, name, ev_ids, provider_owed (what those vehicles cost
    us), expected (what we could bill the rider), collected, missed (still
    outstanding), recovered, pending, collection_pct, recovery_pct,
    settled_via (companies whose payout actually collected the rent).

    ``unheld`` lists days in the window that no rider was on the hook for, per
    EV, with what they cost us — the money this view used to drop on the floor.
    """
    prov = _norm_provider(provider)
    rows = conn.execute(
        """
        SELECT l.assigned_person_id                       AS person_id,
               COALESCE(pr.display_name, '(unknown)')     AS name,
               GROUP_CONCAT(DISTINCT l.ev_id)             AS ev_ids,
               COALESCE(SUM(l.provider_cost), 0)          AS provider_owed,
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
        out_rows.append(
            {
                "person_id": r["person_id"],
                "name": r["name"],
                "ev_ids": r["ev_ids"] or "",
                "provider_owed": round(float(r["provider_owed"] or 0), 2),
                "expected": expected,
                "collected": collected,
                "missed": missed,  # still outstanding for the window
                "recovered": round(float(r["recovered"] or 0), 2),
                "pending": round(float(r["pending"] or 0), 2),
                "collection_pct": round(100.0 * collected / expected, 1) if expected else 0.0,
                # Against what the vehicle cost us, not against what we
                # decided to bill: the only percentage that says whether the
                # unit paid for itself.
                "recovery_pct": (
                    round(100.0 * collected / float(r["provider_owed"]), 1)
                    if float(r["provider_owed"] or 0)
                    else 0.0
                ),
                "settled_via": r["settled_via"] or "",
            }
        )

    # Days on our books that nobody was on the hook for. Unassigned, or
    # assigned but not billable to the rider — either way we owed the provider
    # for them and could bill nobody, which is exactly the money worth seeing.
    unheld = [
        {
            "ev_id": r["ev_id"],
            "status": r["status"],
            "days": int(r["days"] or 0),
            "provider_owed": round(float(r["provider_owed"] or 0), 2),
        }
        for r in conn.execute(
            """
            SELECT l.ev_id, u.status,
                   COUNT(*)                            AS days,
                   COALESCE(SUM(l.provider_cost), 0)   AS provider_owed
            FROM ev_daily_ledger l
            JOIN ev_units  u ON u.ev_id = l.ev_id
            JOIN ev_models m ON m.model_id = u.model_id
            WHERE LOWER(m.provider) = LOWER(?)
              AND l.day BETWEEN ? AND ?
              AND l.assigned_person_id IS NULL
            GROUP BY l.ev_id, u.status
            HAVING COALESCE(SUM(l.provider_cost), 0) > 0
            ORDER BY provider_owed DESC
            """,
            (prov, date_from, date_to),
        ).fetchall()
    ]

    def s(key: str) -> float:
        return round(sum(x[key] for x in out_rows), 2)

    exp_t, col_t = s("expected"), s("collected")
    owed_t = s("provider_owed")
    unheld_owed = round(sum(x["provider_owed"] for x in unheld), 2)
    totals = {
        "provider_owed": owed_t,
        # What we owed for vehicles nobody was billed for. Not part of
        # provider_owed above, which is per rider — this is the remainder.
        "unheld_owed": unheld_owed,
        "unheld_evs": len(unheld),
        "expected": exp_t,
        "collected": col_t,
        "missed": s("missed"),
        "recovered": s("recovered"),
        "pending": s("pending"),
        "collection_pct": round(100.0 * col_t / exp_t, 1) if exp_t else 0.0,
        "recovery_pct": (
            round(100.0 * col_t / (owed_t + unheld_owed), 1) if (owed_t + unheld_owed) else 0.0
        ),
        "rider_count": len(out_rows),
    }
    return {
        "provider": prov,
        "from": date_from,
        "to": date_to,
        "rows": out_rows,
        "unheld": unheld,
        "totals": totals,
    }
