"""EV Rent Details — per cycle per company.

Drives the EV Rent Details dashboard. For every (company, cycle_start,
cycle_end) we've processed, returns four split numbers:

  * expected_rent    — full rent the rider owed for the cycle.
  * collected_rent   — portion the rider's payout actually covered this cycle
                       (from RENT_COLLECTED events). The unpaid portion rolls
                       into general dues and is recovered automatically next
                       cycle.
  * rolled_forward   — present-but-couldn't-fully-pay portion that became dues
                       (= expected_rent - collected_rent for present riders).
  * arrears_rent     — riders who were absent from the cycle file. Their rent
                       rolls into EV-arrears (sum of |RENT_MISSED.amount|).

Per-rider status:
  * paid     — collected == expected (no shortfall)
  * partial  — present but only part of rent collected; rest in dues
  * inactive — absent from the cycle file; rent in EV-arrears

Two-company-rider safety: rent is only ever logged at one company per cycle
per person (the engine picks the deduction company); we read RENT logs as the
truth, so a rider at both Spencer's and Myntra contributes to whichever
company actually billed them. No double-counting.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from payout.api.auth import get_current_user
from payout.db import get_connection

router = APIRouter()


@router.get("")
def ev_rent_details(
    company: Optional[str] = None,
    cycle_start: Optional[str] = None,
    cycle_end: Optional[str] = None,
    latest_only: bool = True,
    _: dict = Depends(get_current_user),
) -> list[dict]:
    where = ("t.event_type IN ('RENT', 'RENT_COLLECTED', 'RENT_MISSED', "
             "                  'RENT_RECOVERED', 'XC_RENT_RECOVERED')")
    params: list = []
    if company:
        where += " AND t.company = ?"; params.append(company)
    if cycle_start:
        where += " AND t.cycle_start = ?"; params.append(cycle_start)
    if cycle_end:
        where += " AND t.cycle_end = ?"; params.append(cycle_end)
    # latest_only narrows to the most recent cycle_end per company.
    if latest_only and not (cycle_start or cycle_end):
        where += (
            " AND (t.company, t.cycle_end) IN "
            "(SELECT t2.company, MAX(t2.cycle_end) FROM transactions t2 "
            " WHERE t2.event_type IN "
            "  ('RENT','RENT_COLLECTED','RENT_MISSED','RENT_RECOVERED','XC_RENT_RECOVERED') "
            " GROUP BY t2.company)"
        )

    with get_connection() as conn:
        # collected_rent below = money applied to EV rent THIS cycle, including
        # recoveries of prior-cycle pending (XC_RENT_RECOVERED) and prior-cycle
        # missed-rent arrears (RENT_RECOVERED). That way Spencer's-cycle
        # recoveries of Blitz's earlier shortfall land in the green column
        # rather than disappearing into "arrears recovered" elsewhere.
        cycle_rows = conn.execute(
            f"SELECT t.company, t.cycle_start, t.cycle_end, "
            f"       SUM(CASE WHEN t.event_type='RENT'           THEN -t.amount ELSE 0 END) AS expected_present, "
            f"       SUM(CASE WHEN t.event_type IN ('RENT_COLLECTED','XC_RENT_RECOVERED','RENT_RECOVERED') "
            f"                                                   THEN  t.amount ELSE 0 END) AS collected_rent, "
            f"       SUM(CASE WHEN t.event_type IN ('XC_RENT_RECOVERED','RENT_RECOVERED') "
            f"                                                   THEN  t.amount ELSE 0 END) AS prior_recovered, "
            f"       SUM(CASE WHEN t.event_type='RENT_MISSED'    THEN -t.amount ELSE 0 END) AS arrears_rent, "
            f"       COUNT(DISTINCT t.person_id) AS rider_count "
            f"FROM transactions t "
            f"WHERE {where} "
            f"GROUP BY t.company, t.cycle_start, t.cycle_end "
            f"ORDER BY t.cycle_end DESC, t.company",
            params,
        ).fetchall()

        result: list[dict] = []
        for cyc in cycle_rows:
            expected_present_total = float(cyc["expected_present"] or 0)
            collected_total = float(cyc["collected_rent"] or 0)
            arrears_total = float(cyc["arrears_rent"] or 0)
            # LEGACY CYCLE FALLBACK: cycles processed before the RENT_COLLECTED
            # event existed have RENT but no RENT_COLLECTED. If that's the case
            # (collected total is zero for a cycle that DID record rent), treat
            # the cycle as legacy and assume RENT itself was the collected
            # amount — no shortfall, everyone marked "paid".
            legacy = expected_present_total > 0 and collected_total == 0

            rider_rows = conn.execute(
                "SELECT t.person_id, t.rider_id, pr.display_name, "
                "       SUM(CASE WHEN t.event_type='RENT'           THEN -t.amount ELSE 0 END) AS expected_present, "
                "       SUM(CASE WHEN t.event_type IN ('RENT_COLLECTED','XC_RENT_RECOVERED','RENT_RECOVERED') "
                "                                                   THEN  t.amount ELSE 0 END) AS collected_rent, "
                "       SUM(CASE WHEN t.event_type IN ('XC_RENT_RECOVERED','RENT_RECOVERED') "
                "                                                   THEN  t.amount ELSE 0 END) AS prior_recovered, "
                "       SUM(CASE WHEN t.event_type='RENT_MISSED'    THEN -t.amount ELSE 0 END) AS arrears_rent, "
                "       MAX(CASE WHEN t.event_type='RENT'           THEN t.days END) AS days_billed, "
                "       (SELECT rm.hub FROM rider_master rm "
                "          WHERE rm.person_id = t.person_id AND rm.company = t.company "
                "          LIMIT 1) AS hub "
                "FROM transactions t "
                "LEFT JOIN person_registry pr ON pr.person_id = t.person_id "
                "WHERE t.event_type IN ('RENT', 'RENT_COLLECTED', 'RENT_MISSED', "
                "                       'XC_RENT_RECOVERED', 'RENT_RECOVERED') "
                "  AND t.company = ? AND t.cycle_start = ? AND t.cycle_end = ? "
                "GROUP BY t.person_id, t.rider_id, pr.display_name "
                "ORDER BY arrears_rent DESC, (expected_present - collected_rent) DESC, pr.display_name",
                (cyc["company"], cyc["cycle_start"], cyc["cycle_end"]),
            ).fetchall()
            by_rider = []
            for r in rider_rows:
                expected_present = float(r["expected_present"] or 0)
                collected = float(r["collected_rent"] or 0)
                prior_recovered = float(r["prior_recovered"] or 0)
                arrears = float(r["arrears_rent"] or 0)
                if legacy and collected == 0 and expected_present > 0:
                    collected = expected_present
                # rolled_forward is based ONLY on current cycle's rent vs the
                # portion of collected that went to current rent; prior
                # recoveries don't reduce roll-forward.
                current_collected = max(0.0, collected - prior_recovered)
                rolled_forward = max(0.0, expected_present - current_collected)

                # Look ahead: did a later cycle pay down this cycle's miss /
                # shortfall? If so, the status downgrades from inactive/partial
                # to 'recovered'.
                future_arrears_recovered = 0.0
                future_xc_recovered = 0.0
                if arrears > 0 or rolled_forward > 0:
                    # Include recoveries that share the same cycle_end (e.g.,
                    # Myntra cycle 06-01..06-07 missed; Spencer's cycle
                    # 06-01..06-07 covered it). Just exclude *this* exact
                    # (company, cycle_start, cycle_end) so we don't self-attribute.
                    fa = conn.execute(
                        "SELECT COALESCE(SUM(amount), 0) AS s FROM transactions "
                        "WHERE person_id=? AND event_type='RENT_RECOVERED' "
                        "  AND cycle_end >= ? "
                        "  AND NOT (company=? AND cycle_start=? AND cycle_end=?)",
                        (r["person_id"], cyc["cycle_end"],
                         cyc["company"], cyc["cycle_start"], cyc["cycle_end"]),
                    ).fetchone()
                    future_arrears_recovered = float(fa["s"] or 0)
                    fx = conn.execute(
                        "SELECT COALESCE(SUM(amount), 0) AS s FROM transactions "
                        "WHERE person_id=? AND event_type='XC_RENT_RECOVERED' "
                        "  AND cycle_end >= ? "
                        "  AND NOT (company=? AND cycle_start=? AND cycle_end=?)",
                        (r["person_id"], cyc["cycle_end"],
                         cyc["company"], cyc["cycle_start"], cyc["cycle_end"]),
                    ).fetchone()
                    future_xc_recovered = float(fx["s"] or 0)
                if arrears > 0:
                    expected = arrears
                    if future_arrears_recovered >= arrears - 0.005:
                        status = "recovered"
                    elif future_arrears_recovered > 0.005:
                        status = "partial_recovered"
                    else:
                        status = "inactive"
                elif expected_present > 0 and current_collected >= expected_present - 0.005:
                    expected = expected_present
                    status = "paid"
                elif expected_present > 0 and current_collected > 0:
                    expected = expected_present
                    if future_xc_recovered >= rolled_forward - 0.005:
                        status = "recovered"
                    elif future_xc_recovered > 0.005:
                        status = "partial_recovered"
                    else:
                        status = "partial"
                elif expected_present > 0:
                    expected = expected_present
                    if future_xc_recovered >= expected_present - 0.005:
                        status = "recovered"
                    elif future_xc_recovered > 0.005:
                        status = "partial_recovered"
                    else:
                        status = "partial"
                else:
                    expected = 0.0
                    status = "paid"
                by_rider.append({
                    "person_id": r["person_id"],
                    "rider_id": r["rider_id"],
                    "display_name": r["display_name"],
                    "hub": r["hub"],
                    "expected_rent": round(expected, 2),
                    "collected_rent": round(collected, 2),
                    "prior_recovered": round(prior_recovered, 2),
                    "rolled_forward": round(rolled_forward if status != "inactive" else 0.0, 2),
                    "arrears_rent": round(arrears, 2),
                    "days_billed": r["days_billed"],
                    "status": status,
                })
            # Cycle-level totals respect the legacy fallback too.
            prior_recovered_total = float(cyc["prior_recovered"] or 0)
            if legacy:
                collected_total = expected_present_total
            current_collected_total = max(0.0, collected_total - prior_recovered_total)
            rolled_forward_total = max(0.0, expected_present_total - current_collected_total)
            result.append({
                "company": cyc["company"],
                "cycle_start": cyc["cycle_start"],
                "cycle_end": cyc["cycle_end"],
                "expected_rent": round(expected_present_total + arrears_total, 2),
                "collected_rent": round(collected_total, 2),
                "prior_recovered": round(prior_recovered_total, 2),
                "rolled_forward": round(rolled_forward_total, 2),
                "arrears_rent": round(arrears_total, 2),
                "rider_count": cyc["rider_count"],
                "legacy": legacy,
                "by_rider": by_rider,
            })
    return result
