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

from fastapi import APIRouter, Depends

from payout.api.auth import get_current_user
from payout.db import get_connection

router = APIRouter()


def _split_companies(s: str | None) -> list[str]:
    """Comma-separated → list. Empty / None → empty list."""
    if not s:
        return []
    return [c.strip() for c in s.split(",") if c.strip()]


@router.get("")
def ev_rent_details(
    company: str | None = None,  # legacy single (back-compat)
    companies: str | None = None,  # comma-separated multi
    cycle_start: str | None = None,
    cycle_end: str | None = None,
    latest_only: bool = True,
    _: dict = Depends(get_current_user),
) -> list[dict]:
    cos = _split_companies(companies) or ([company] if company else [])
    where = (
        "t.event_type IN ('RENT', 'RENT_COLLECTED', 'RENT_MISSED', "
        "                  'RENT_RECOVERED', 'XC_RENT_RECOVERED')"
        " AND t.company IS NOT NULL AND t.company <> ''"
    )
    params: list = []
    if cos:
        ph = ",".join("?" for _ in cos)
        where += f" AND t.company IN ({ph})"
        params.extend(cos)
    if cycle_start:
        where += " AND t.cycle_start = ?"
        params.append(cycle_start)
    if cycle_end:
        where += " AND t.cycle_end = ?"
        params.append(cycle_end)
    # latest_only narrows to the most recent cycle_end per company.
    # IMPORTANT: we filter on event_type='RENT' (and the engine's RENT_MISSED
    # for absence-only cycles) to find the "real" latest cycle. Otherwise a
    # manual rent payment (RENT_COLLECTED with a single-day "cycle") can beat
    # the actual weekly cycle in the MAX(cycle_end) comparison and silently
    # truncate the rider list to whoever paid by hand.
    if latest_only and not (cycle_start or cycle_end):
        where += (
            " AND (t.company, t.cycle_end) IN "
            "(SELECT t2.company, MAX(t2.cycle_end) FROM transactions t2 "
            " WHERE t2.event_type IN ('RENT','RENT_MISSED') "
            " GROUP BY t2.company)"
        )

    with get_connection() as conn:
        # collected_rent below = money applied to EV rent THIS cycle, including
        # recoveries of prior-cycle pending (XC_RENT_RECOVERED) and prior-cycle
        # missed-rent arrears (RENT_RECOVERED). That way Spencer's-cycle
        # recoveries of Blitz's earlier shortfall land in the green column
        # rather than disappearing into "arrears recovered" elsewhere.
        #
        # ORDER BY ASC so the FIFO recovery walk below allocates older cycles'
        # arrears first. Result list is reversed at the end for display.
        cycle_rows = conn.execute(
            f"SELECT t.company, t.cycle_start, t.cycle_end, "
            f"       SUM(CASE WHEN t.event_type='RENT'           THEN -t.amount ELSE 0 END) AS expected_present, "  # noqa: E501
            f"       SUM(CASE WHEN t.event_type IN ('RENT_COLLECTED','XC_RENT_RECOVERED','RENT_RECOVERED') "  # noqa: E501
            f"                                                   THEN  t.amount ELSE 0 END) AS collected_rent, "  # noqa: E501
            f"       SUM(CASE WHEN t.event_type IN ('XC_RENT_RECOVERED','RENT_RECOVERED') "
            f"                                                   THEN  t.amount ELSE 0 END) AS prior_recovered, "  # noqa: E501
            f"       SUM(CASE WHEN t.event_type='RENT_MISSED'    THEN -t.amount ELSE 0 END) AS arrears_rent, "  # noqa: E501
            f"       COUNT(DISTINCT t.person_id) AS rider_count "
            f"FROM transactions t "
            f"WHERE {where} "
            f"GROUP BY t.company, t.cycle_start, t.cycle_end "
            f"HAVING SUM(CASE WHEN t.event_type='RENT' THEN -t.amount ELSE 0 END) > 0 "
            f"    OR SUM(CASE WHEN t.event_type='RENT_MISSED' THEN -t.amount ELSE 0 END) > 0 "
            f"ORDER BY t.cycle_end ASC, t.company",
            params,
        ).fetchall()

        # ── Person-level recovery pools ───────────────────────────────────
        # Manual rent payments and the engine's automatic claw-backs both
        # log RENT_RECOVERED (for missed-rent arrears) and XC_RENT_RECOVERED
        # (for current-cycle shortfall) — but with cycle_start/cycle_end
        # anchored to the *payment's* cycle, not the missed cycle being
        # paid down. The old per-cycle attribution used `cycle_end >= ?`
        # which silently dropped recoveries dated before the miss (e.g.
        # operator collects rent for the latest-cycle that's earlier than
        # a still-outstanding older miss). It also let two missed cycles
        # each claim the same recovery via per-cycle `min()` clamping.
        #
        # Fix: pool RENT_RECOVERED / XC_RENT_RECOVERED per person across
        # all history, then walk cycles oldest-first and allocate FIFO.
        # The recovery's own cycle tag becomes irrelevant — what matters
        # is "how much has this person paid back, total".
        arrears_pool: dict[int, float] = {}
        xc_pool: dict[int, float] = {}
        for pr in conn.execute(
            "SELECT person_id, event_type, COALESCE(SUM(amount), 0) AS s "
            "FROM transactions "
            "WHERE event_type IN ('RENT_RECOVERED', 'XC_RENT_RECOVERED') "
            "GROUP BY person_id, event_type"
        ).fetchall():
            if pr["event_type"] == "RENT_RECOVERED":
                arrears_pool[pr["person_id"]] = float(pr["s"] or 0)
            else:
                xc_pool[pr["person_id"]] = float(pr["s"] or 0)

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
                "       SUM(CASE WHEN t.event_type='RENT'           THEN -t.amount ELSE 0 END) AS expected_present, "  # noqa: E501
                "       SUM(CASE WHEN t.event_type IN ('RENT_COLLECTED','XC_RENT_RECOVERED','RENT_RECOVERED') "  # noqa: E501
                "                                                   THEN  t.amount ELSE 0 END) AS collected_rent, "  # noqa: E501
                "       SUM(CASE WHEN t.event_type IN ('XC_RENT_RECOVERED','RENT_RECOVERED') "
                "                                                   THEN  t.amount ELSE 0 END) AS prior_recovered, "  # noqa: E501
                "       SUM(CASE WHEN t.event_type='RENT_MISSED'    THEN -t.amount ELSE 0 END) AS arrears_rent, "  # noqa: E501
                "       MAX(CASE WHEN t.event_type='RENT'           THEN t.days END) AS days_billed, "  # noqa: E501
                "       MAX((SELECT rm.hub FROM rider_master rm "
                "          WHERE rm.person_id = t.person_id AND rm.company = t.company "
                "          LIMIT 1)) AS hub "
                "FROM transactions t "
                "LEFT JOIN person_registry pr ON pr.person_id = t.person_id "
                "WHERE t.event_type IN ('RENT', 'RENT_COLLECTED', 'RENT_MISSED', "
                "                       'XC_RENT_RECOVERED', 'RENT_RECOVERED') "
                "  AND t.company = ? AND t.cycle_start = ? AND t.cycle_end = ? "
                "GROUP BY t.person_id, t.rider_id, pr.display_name "
                "ORDER BY arrears_rent DESC, (SUM(CASE WHEN t.event_type='RENT' THEN -t.amount ELSE 0 END) - SUM(CASE WHEN t.event_type IN ('RENT_COLLECTED','XC_RENT_RECOVERED','RENT_RECOVERED') THEN t.amount ELSE 0 END)) DESC, pr.display_name",  # noqa: E501
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

                # FIFO allocation from the per-person recovery pool. Walking
                # cycles oldest-first means earlier missed cycles consume the
                # pool first — no double-counting, and we don't depend on the
                # recovery row's cycle_start/cycle_end being aligned with the
                # missed cycle (manual rent payments often anchor to a much
                # earlier cycle than the one being paid down).
                pid = r["person_id"]
                future_arrears_recovered = 0.0
                future_xc_recovered = 0.0
                if arrears > 0:
                    avail = arrears_pool.get(pid, 0.0)
                    take = min(arrears, avail)
                    future_arrears_recovered = take
                    arrears_pool[pid] = avail - take
                if rolled_forward > 0:
                    avail = xc_pool.get(pid, 0.0)
                    take = min(rolled_forward, avail)
                    future_xc_recovered = take
                    xc_pool[pid] = avail - take
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
                by_rider.append(
                    {
                        "person_id": r["person_id"],
                        "rider_id": r["rider_id"],
                        "display_name": r["display_name"],
                        "hub": r["hub"],
                        "expected_rent": round(expected, 2),
                        "collected_rent": round(collected, 2),
                        "prior_recovered": round(prior_recovered, 2),
                        "rolled_forward": round(rolled_forward if status != "inactive" else 0.0, 2),
                        "arrears_rent": round(arrears, 2),
                        "future_arrears_recovered": round(
                            min(arrears, future_arrears_recovered), 2
                        ),
                        "future_xc_recovered": round(min(rolled_forward, future_xc_recovered), 2),
                        "days_billed": r["days_billed"],
                        "status": status,
                    }
                )
            # Cycle-level totals respect the legacy fallback too.
            prior_recovered_total = float(cyc["prior_recovered"] or 0)
            if legacy:
                collected_total = expected_present_total
            current_collected_total = max(0.0, collected_total - prior_recovered_total)
            rolled_forward_total = max(0.0, expected_present_total - current_collected_total)
            # Cycle-level "eventually recovered" — sums the per-rider future
            # recoveries, capped at each rider's original shortfall so we
            # don't over-claim recovery. Lets the UI show net arrears for
            # the cycle row, healing visually when Spencer's claws back
            # Blitz's miss in a later week.
            arrears_recovered_later = round(sum(r["future_arrears_recovered"] for r in by_rider), 2)
            rolled_recovered_later = round(sum(r["future_xc_recovered"] for r in by_rider), 2)
            arrears_net = max(0.0, arrears_total - arrears_recovered_later)
            rolled_net = max(0.0, rolled_forward_total - rolled_recovered_later)
            result.append(
                {
                    "company": cyc["company"],
                    "cycle_start": cyc["cycle_start"],
                    "cycle_end": cyc["cycle_end"],
                    "expected_rent": round(expected_present_total + arrears_total, 2),
                    "collected_rent": round(collected_total, 2),
                    "collected_current": round(current_collected_total, 2),
                    "prior_recovered": round(prior_recovered_total, 2),
                    "rolled_forward": round(rolled_forward_total, 2),
                    "rolled_recovered_later": rolled_recovered_later,
                    "rolled_forward_net": round(rolled_net, 2),
                    "arrears_rent": round(arrears_total, 2),
                    "arrears_recovered_later": arrears_recovered_later,
                    "arrears_net": round(arrears_net, 2),
                    "rider_count": cyc["rider_count"],
                    "legacy": legacy,
                    "by_rider": by_rider,
                }
            )
    # FIFO walk was oldest-first; display expects newest-first.
    result.reverse()
    return result
