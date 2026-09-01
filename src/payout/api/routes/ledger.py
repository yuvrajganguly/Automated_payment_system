"""Ledger routes: per-person transactions, manual adjustments."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from payout.api.auth import get_current_user, require_admin
from payout.api.schemas import AdjustmentIn, RentPaymentIn, TransactionOut
from payout.db import get_connection
from payout.domain.adjustments import post_adjustment
from payout.exports import xlsx_response
from payout.money import to_paise

router = APIRouter()


@router.get("/export")
def export_transactions(
    event_type: str | None = None,
    company: str | None = None,
    limit: int = 5000,
    _: dict = Depends(get_current_user),
):
    """Recent transactions as a styled .xlsx download."""
    sql = (
        "SELECT id, person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, days, remarks, created_at, created_by "
        "FROM transactions WHERE 1=1 "
    )
    params: list = []
    if event_type:
        sql += " AND event_type=? "
        params.append(event_type)
    if company:
        sql += " AND company=? "
        params.append(company)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(max(limit, 1), 100000))
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    headers = [
        "ID",
        "Person ID",
        "Rider ID",
        "Company",
        "Cycle Start",
        "Cycle End",
        "Event",
        "Amount",
        "Balance After",
        "Days",
        "Remarks",
        "When",
        "By",
    ]
    out = [
        (
            r["id"],
            r["person_id"],
            r["rider_id"],
            r["company"],
            r["cycle_start"],
            r["cycle_end"],
            r["event_type"],
            r["amount"],
            r["balance_after"],
            r["days"] if r["days"] is not None else "",
            r["remarks"] or "",
            r["created_at"] or "",
            r["created_by"] or "",
        )
        for r in rows
    ]
    return xlsx_response(
        filename_stem="transactions",
        sheet_name="TXNS",
        headers=headers,
        rows=out,
        numeric_cols=(8, 9),
        money_cols=(8, 9),
        left_align_cols=(11, 13),
    )


@router.get("", response_model=list[TransactionOut])
def list_recent_transactions(
    event_type: str | None = None,
    company: str | None = None,
    limit: int = 200,
    _: dict = Depends(get_current_user),
) -> list[TransactionOut]:
    """Global transaction feed across all persons (newest first)."""
    sql = (
        "SELECT id, person_id, rider_id, company, cycle_start, cycle_end, event_type, "
        "amount, balance_after, days, remarks, created_at, created_by "
        "FROM transactions WHERE 1=1 "
    )
    params: list = []
    if event_type:
        sql += " AND event_type=? "
        params.append(event_type)
    if company:
        sql += " AND company=? "
        params.append(company)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(min(max(limit, 1), 1000))
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [TransactionOut(**dict(r)) for r in rows]


@router.get("/{person_id}", response_model=list[TransactionOut])
def get_ledger(
    person_id: int,
    event_type: str | None = None,
    limit: int = 200,
    _: dict = Depends(get_current_user),
) -> list[TransactionOut]:
    sql = (
        "SELECT id, person_id, rider_id, company, cycle_start, cycle_end, event_type, "
        "amount, balance_after, days, remarks, created_at, created_by "
        "FROM transactions WHERE person_id=? "
    )
    params: list = [person_id]
    if event_type:
        sql += " AND event_type=? "
        params.append(event_type)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [TransactionOut(**dict(r)) for r in rows]


def _resolve_person_id(conn, *, person_id, rider_id, company):
    pid = person_id
    if not pid and rider_id:
        if company:
            row = conn.execute(
                "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
                (rider_id, company),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT person_id FROM rider_master WHERE rider_id=? LIMIT 1", (rider_id,)
            ).fetchone()
        if row:
            pid = row["person_id"]
    if not pid:
        raise HTTPException(404, "Person not found (provide person_id or rider_id)")
    return pid


@router.post("/rent-payment")
def post_rent_payment(body: RentPaymentIn, user: dict = Depends(require_admin)) -> dict:
    """Record a manual rent payment.

    A rider walked in (or UPI'd outside the bank reconciliation) and paid some
    rent. We split the amount:

      1. **Arrears first.** Any outstanding ev_arrears.outstanding is paid down
         and logged as RENT_RECOVERED. EV Rent Details reads this as recovered
         rent for the prior cycle.
      2. **Current cycle rent next.** The remainder is logged as RENT_COLLECTED.
         EV Rent Details reads this as collected rent for the current cycle.

    Either way the running balance is credited by the full amount so the
    Person ledger and the Arrears/Dues view agree.
    """
    if body.amount <= 0:
        raise HTTPException(400, "Amount must be positive.")
    paid_on = body.paid_on or date.today().isoformat()
    note = (body.remarks or "manual rent payment").strip()

    with get_connection() as conn:
        pid = _resolve_person_id(
            conn, person_id=body.person_id, rider_id=body.rider_id, company=body.company
        )
        # Decide which (company, rider_id) to attach the RENT_COLLECTED row to.
        # Under first-cycle-wins, the actual RENT event may have been charged
        # at a non-deduction company (whichever processed first). The
        # collection must land at the SAME company so the EV Rent Details
        # math balances per (company, cycle). Walk the cycle window backwards
        # from the explicit override → most-recent RENT event for this person
        # → deduction company → body's company.
        if body.period_start and body.period_end:
            anchor = conn.execute(
                "SELECT company, rider_id FROM transactions "
                "WHERE person_id=? AND event_type='RENT' "
                "  AND cycle_start=? AND cycle_end=? "
                "ORDER BY id DESC LIMIT 1",
                (pid, body.period_start, body.period_end),
            ).fetchone()
        else:
            anchor = conn.execute(
                "SELECT company, rider_id FROM transactions "
                "WHERE person_id=? AND event_type='RENT' "
                "ORDER BY id DESC LIMIT 1",
                (pid,),
            ).fetchone()
        if anchor:
            company = anchor["company"]
            rider_id = anchor["rider_id"]
        else:
            pr = conn.execute(
                "SELECT deduction_company, deduction_rider_id "
                "FROM person_registry WHERE person_id=?",
                (pid,),
            ).fetchone()
            company = (pr["deduction_company"] if pr else None) or body.company or ""
            rider_id = (pr["deduction_rider_id"] if pr else None) or body.rider_id or ""

        # Decide which cycle window this payment covers.
        #   1. If the caller provided period_start/period_end, use them. This
        #      is the explicit "this covers 8 Jun – 14 Jun" case.
        #   2. Otherwise fall back to the rider's most recent RENT cycle so
        #      RENT_COLLECTED still slots into something the EV Rent Details
        #      aggregation can pick up.
        #   3. As a last resort, fall back to the deduction company's most
        #      recent processed cycle (any RENT event for any rider on that
        #      company). Single-day "cycles" (cs == ce == paid_on) cause the
        #      EV Rent Details "latest cycle" picker to glitch, so we go to
        #      lengths to find a real weekly cycle to attach to.
        if body.period_start and body.period_end:
            cs, ce = body.period_start, body.period_end
        else:
            last = conn.execute(
                "SELECT cycle_start, cycle_end FROM transactions "
                "WHERE person_id=? AND event_type='RENT' "
                "ORDER BY id DESC LIMIT 1",
                (pid,),
            ).fetchone()
            if last:
                cs, ce = last["cycle_start"], last["cycle_end"]
            else:
                # Try the deduction company's latest RENT cycle.
                co_last = None
                if company:
                    co_last = conn.execute(
                        "SELECT cycle_start, cycle_end FROM transactions "
                        "WHERE company=? AND event_type='RENT' "
                        "ORDER BY id DESC LIMIT 1",
                        (company,),
                    ).fetchone()
                if co_last:
                    cs, ce = co_last["cycle_start"], co_last["cycle_end"]
                else:
                    # Absolute last resort: a 7-day window ending paid_on.
                    # Prevents the degenerate single-day cycle that pollutes
                    # the EV Rent Details "latest cycle" picker.
                    from datetime import date as _date
                    from datetime import timedelta

                    ce_dt = _date.fromisoformat(paid_on)
                    cs = (ce_dt - timedelta(days=6)).isoformat()
                    ce = paid_on

        # Read current balance + arrears outstanding.
        bal_row = conn.execute(
            "SELECT current_balance FROM balances WHERE person_id=?", (pid,)
        ).fetchone()
        balance = bal_row["current_balance"] if bal_row else 0.0
        arr_row = conn.execute(
            "SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)
        ).fetchone()
        arr_out = arr_row["outstanding"] if arr_row else 0.0

        applied_to_arrears = 0.0
        applied_to_rent = 0.0
        remaining = to_paise(body.amount)

        # IMPORTANT — the balance does NOT change here.
        # Background: RENT_MISSED only touches ev_arrears.outstanding; it never
        # debits the balance. Likewise the engine's normal rent collection
        # (PAYOUT + RENT + RENT_COLLECTED) nets to zero on the balance — the
        # rider goes home with (payout - rent) released as cash. A manual rent
        # payment is the same shape: the rider hands over cash that mirrors
        # what the payout would have deducted, so the ledger balance must stay
        # put. The audit RENT_RECOVERED / RENT_COLLECTED rows still get logged
        # with the *unchanged* balance_after so the trail is clear.

        # 1) Arrears first.
        if arr_out > 0 and remaining > 0:
            applied_to_arrears = round(min(remaining, arr_out), 2)
            conn.execute(
                "UPDATE ev_arrears SET total_recovered = total_recovered + ?, "
                "outstanding = outstanding - ?, last_updated=? "
                "WHERE person_id=?",
                (applied_to_arrears, applied_to_arrears, paid_on, pid),
            )
            recovery_txn_id = conn.execute(
                "INSERT INTO transactions (person_id, rider_id, company, "
                "cycle_start, cycle_end, event_type, amount, balance_after, "
                "remarks, created_by) "
                "VALUES (?,?,?,?,?,'RENT_RECOVERED',?,?,?,?)",
                (
                    pid,
                    rider_id,
                    company,
                    cs,
                    ce,
                    applied_to_arrears,
                    balance,
                    f"manual rent — arrears ({note})",
                    user["email"],
                ),
            ).lastrowid
            remaining = round(remaining - applied_to_arrears, 2)
            # Daily ledger: heal the oldest 'missed' day-rows for this person
            # up to the recovered amount. The Provider Weekly report would
            # otherwise still show these days as missed.
            from payout.domain.ev_daily import attribute_recovery

            attribute_recovery(
                conn,
                person_id=pid,
                recovery_event_id=recovery_txn_id,
                amount=applied_to_arrears,
            )

        # 2) Current cycle rent.
        collected_txn_id = None
        if remaining > 0:
            applied_to_rent = round(remaining, 2)
            collected_txn_id = conn.execute(
                "INSERT INTO transactions (person_id, rider_id, company, "
                "cycle_start, cycle_end, event_type, amount, balance_after, "
                "remarks, created_by) "
                "VALUES (?,?,?,?,?,'RENT_COLLECTED',?,?,?,?)",
                (
                    pid,
                    rider_id,
                    company,
                    cs,
                    ce,
                    applied_to_rent,
                    balance,
                    f"manual rent payment ({note})",
                    user["email"],
                ),
            ).lastrowid
            # Daily ledger: heal any still-'missed' days first (safety net if
            # the arrears walk above didn't soak them all up)...
            from payout.domain.ev_daily import attribute_pending, attribute_recovery

            healed = attribute_recovery(
                conn,
                person_id=pid,
                recovery_event_id=collected_txn_id,
                amount=applied_to_rent,
            )
            # ...then, when the payment names an explicit coverage window, mark
            # the leftover against 'pending' days in that window as 'billed', so
            # a manual pre-payment for a not-yet-run cycle reads as collected
            # (not pending) on the dashboard and provider reconciliation.
            leftover = round(applied_to_rent - (healed or 0.0), 2)
            if leftover > 0 and body.period_start and body.period_end:
                attribute_pending(
                    conn,
                    person_id=pid,
                    event_id=collected_txn_id,
                    amount=leftover,
                    day_from=cs,
                    day_to=ce,
                )

        # If the caller specified a coverage window and the payment actually
        # paid down rent, advance the EV's rent_charged_through so the engine
        # won't re-charge the same days. Forward-only (monotonic) — and, since
        # the 01-Jul-2026 incident, ONLY as far as the money reaches: Rs.1,250
        # once advanced a meter five weeks, silently writing off ~Rs.5,300.
        # Only applied_to_rent buys new meter days; arrears money repays days
        # already accounted as missed. Going further needs force_advance=true.
        advanced_to = None
        if body.period_end and (applied_to_rent > 0 or applied_to_arrears > 0):
            row = conn.execute(
                "SELECT a.assignment_id, a.rent_charged_through, m.weekly_rate "
                "FROM ev_assignments a "
                "JOIN ev_units u ON u.ev_id = a.ev_id "
                "JOIN ev_models m ON m.model_id = u.model_id "
                "WHERE a.person_id=? AND a.returned_date IS NULL",
                (pid,),
            ).fetchone()
            if row:
                cur_through = row["rent_charged_through"] or ""
                if body.period_end > cur_through:
                    from payout.domain.rent import allowed_paid_through

                    covered = (
                        allowed_paid_through(
                            cur_through=cur_through or None,
                            period_start=body.period_start,
                            rent_paise=int(applied_to_rent),
                            weekly_rate=float(row["weekly_rate"]),
                        )
                        or cur_through
                    )
                    target = body.period_end
                    if body.period_end > covered:
                        if not body.force_advance:
                            day_rate = float(row["weekly_rate"]) / 7.0
                            from datetime import date as _d

                            gap_days = (
                                (_d.fromisoformat(body.period_end) - _d.fromisoformat(covered)).days
                                if covered
                                else None
                            )
                            gap_rs = (gap_days * day_rate / 100.0) if gap_days else None
                            raise HTTPException(
                                400,
                                detail=(
                                    f"This payment covers rent only through "
                                    f"{covered or 'no new days'} (Rs.{applied_to_rent / 100.0:,.2f} "  # noqa: E501
                                    f"toward rent after arrears), but period_end is "
                                    f"{body.period_end}"
                                    + (
                                        f" — {gap_days} unpaid days (~Rs.{gap_rs:,.0f}) "
                                        f"would be marked paid and become unbillable."
                                        if gap_days
                                        else "."
                                    )
                                    + " Reduce period_end, or pass force_advance=true "
                                    "with the reason in remarks (e.g. a waiver)."
                                ),
                            )
                        # explicit, documented override
                    else:
                        target = max(covered, cur_through) if covered else body.period_end
                        target = min(target, body.period_end)
                    if target and target > cur_through:
                        conn.execute(
                            "UPDATE ev_assignments SET rent_charged_through=? "
                            "WHERE assignment_id=?",
                            (target, row["assignment_id"]),
                        )
                        advanced_to = target
                        # Day-ledger: create billed rows for newly covered days
                        # that have no row yet (manual payments used to leave
                        # holes that day-grain reports undercounted).
                        if collected_txn_id and applied_to_rent > 0:
                            from datetime import date as _d2
                            from datetime import timedelta as _td

                            from payout.domain.ev_daily import backfill_billed_days

                            bf_from = (
                                (_d2.fromisoformat(cur_through) + _td(days=1)).isoformat()
                                if cur_through
                                else (body.period_start or target)
                            )
                            backfill_billed_days(
                                conn,
                                person_id=pid,
                                event_id=collected_txn_id,
                                day_from=bf_from,
                                day_to=target,
                            )
        conn.commit()

    return {
        "person_id": pid,
        "applied_to_arrears": applied_to_arrears,
        "applied_to_rent": applied_to_rent,
        "new_balance": balance,
        "covered_window": {"start": cs, "end": ce}
        if (body.period_start and body.period_end)
        else None,
        "rent_charged_through_advanced_to": advanced_to,
    }


@router.post("/adjustments")
def post_adjustment_endpoint(body: AdjustmentIn, user: dict = Depends(require_admin)) -> dict:
    if not body.reason:
        raise HTTPException(400, "Reason is required")
    if not body.amount:
        raise HTTPException(400, "Amount cannot be zero")
    with get_connection() as conn:
        pid = _resolve_person_id(
            conn, person_id=body.person_id, rider_id=body.rider_id, company=body.company
        )
        amt_p = to_paise(body.amount)
        new_balance = post_adjustment(
            conn,
            pid,
            amt_p,
            body.reason,
            user["email"],
            rider_id=body.rider_id or "",
            company=body.company or "",
        )
        conn.commit()
    return {"person_id": pid, "amount": amt_p, "new_balance": new_balance}
