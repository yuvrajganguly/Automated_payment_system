"""Cycle orchestrator: process one company file end-to-end, atomically."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from payout.db import get_connection
from payout.domain.adjustments import post_adjustment
from payout.domain.arrears import (
    apply_settlement, get_cod_arrears,
    record_cod_missed, record_cod_recovery,
    record_missed_rent, record_recovery,
)
from payout.domain.holds import compute_holds, persist_holds
from payout.domain.rent import advance_rent_charged_through, resolve_rent
from payout.parsers import parse_file


@dataclass
class RiderOverride:
    waive_days: int = 0
    waive_all: bool = False
    rent_override: float | None = None
    force_hold: bool = False
    force_release: bool = False


@dataclass
class CycleOverrides:
    per_rider: dict = field(default_factory=dict)
    adjustments: list = field(default_factory=list)


@dataclass
class RiderResult:
    person_id: int
    rider_id: str
    name: str
    hub: str | None
    vehicle: str | None
    company: str
    ev_id: str | None
    model: str | None
    payout: float
    rent: float
    days: int
    arrears_recovered: float
    dues_cleared: float
    prev_balance: float
    released: float
    new_balance: float
    new_arrears: float
    cod_hold: float
    is_hold: bool
    remarks: str
    account_no: str | None
    ifsc: str | None
    # Delivered/completed orders pulled straight from the company file when the
    # company config declares an orders_column. None when not available.
    orders: float | None = None


@dataclass
class InactiveRider:
    person_id: int
    name: str
    rider_ids: list
    ev_id: str | None
    model: str | None
    current_balance: float
    arrears_outstanding: float
    reason: str
    vehicle: str | None = None
    hub: str | None = None


@dataclass
class CycleResult:
    company: str
    cycle_start: date
    cycle_end: date
    pay_rows: list = field(default_factory=list)
    dues_rows: list = field(default_factory=list)
    hold_rows: list = field(default_factory=list)
    inactive_rows: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    unknown_ids: list = field(default_factory=list)
    committed: bool = False
    totals: dict = field(default_factory=dict)


def _iso(d): return d.isoformat() if hasattr(d, "isoformat") else str(d)


def _txn(conn, **kw):
    conn.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, days, remarks, created_by) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (kw["person_id"], kw.get("rider_id", ""), kw.get("company", ""),
         _iso(kw["cycle_start"]), _iso(kw["cycle_end"]),
         kw["event_type"], kw["amount"], kw["balance_after"],
         kw.get("days"), kw.get("remarks", ""), kw.get("created_by", "engine")),
    )


def _lookup(conn, rider_id, company):
    row = conn.execute(
        # Vehicle is derived from EV-assignment status so it's consistent across
        # every rider_master row for the same person — EV when they currently
        # hold an open assignment, BIKE otherwise (default for anyone without
        # an explicit EV). Matches the riders-list endpoint.
        "SELECT rm.person_id, rm.name, rm.hub, "
        "       CASE WHEN ea.assignment_id IS NOT NULL THEN 'EV' ELSE 'BIKE' END "
        "         AS vehicle, "
        "       rm.account_no, rm.ifsc, "
        "       pr.deduction_company, pr.deduction_rider_id "
        "FROM rider_master rm "
        "JOIN person_registry pr ON pr.person_id = rm.person_id "
        "LEFT JOIN ev_assignments ea "
        "  ON ea.person_id = rm.person_id AND ea.returned_date IS NULL "
        "WHERE rm.rider_id=? AND rm.company=?",
        (rider_id, company),
    ).fetchone()
    return dict(row) if row else None


def _balance(conn, pid):
    r = conn.execute("SELECT current_balance FROM balances WHERE person_id=?", (pid,)).fetchone()
    return r["current_balance"] if r else 0.0


def _arrears_out(conn, pid):
    r = conn.execute("SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()
    return r["outstanding"] if r else 0.0


def _set_balance(conn, pid, new_balance, cycle_end):
    conn.execute(
        "INSERT INTO balances (person_id, current_balance, last_updated) VALUES (?,?,?) "
        "ON CONFLICT(person_id) DO UPDATE SET current_balance=excluded.current_balance, "
        "last_updated=excluded.last_updated",
        (pid, new_balance, _iso(cycle_end)),
    )


def _get_pending_xc(conn, pid):
    """Return (amount, origin_company) of the pending cross-company rent
    bucket. (0.0, None) if there's nothing pending."""
    r = conn.execute(
        "SELECT pending_xc_rent, xc_origin_company FROM balances WHERE person_id=?",
        (pid,),
    ).fetchone()
    if not r:
        return (0.0, None)
    return (float(r["pending_xc_rent"] or 0), r["xc_origin_company"])


def _set_pending_xc(conn, pid, amount, origin_company):
    conn.execute(
        "INSERT INTO balances (person_id, current_balance, pending_xc_rent, "
        "xc_origin_company, last_updated) VALUES (?, 0, ?, ?, date('now')) "
        "ON CONFLICT(person_id) DO UPDATE SET "
        "  pending_xc_rent=excluded.pending_xc_rent, "
        "  xc_origin_company=excluded.xc_origin_company, "
        "  last_updated=excluded.last_updated",
        (pid, amount, origin_company),
    )


def _is_multi_company(conn, pid):
    """True if the person has active rider_master rows at 2+ companies."""
    r = conn.execute(
        "SELECT COUNT(DISTINCT company) AS n FROM rider_master "
        "WHERE person_id=? AND is_active=1",
        (pid,),
    ).fetchone()
    return (r["n"] or 0) >= 2


def _mark_present(conn, pid, cycle_end):
    conn.execute(
        "INSERT INTO status_tracking (person_id, status, last_seen, ev_returned) "
        "VALUES (?, 'active', ?, 0) "
        "ON CONFLICT(person_id) DO UPDATE SET status='active', last_seen=excluded.last_seen",
        (pid, _iso(cycle_end)),
    )


def _ev_for(conn, pid):
    r = conn.execute(
        "SELECT a.ev_id, m.model_name FROM ev_assignments a "
        "JOIN ev_units u ON u.ev_id=a.ev_id JOIN ev_models m ON m.model_id=u.model_id "
        "WHERE a.person_id=? AND a.returned_date IS NULL", (pid,),
    ).fetchone()
    return (r["ev_id"], r["model_name"]) if r else (None, None)


def _vehicle_for(conn, pid, company):
    """Derived vehicle: EV if the person has any open EV assignment, BIKE
    otherwise. The ``company`` argument is unused now but kept for callers."""
    del company  # signature-stable, derivation is per-person
    r = conn.execute(
        "SELECT 1 FROM ev_assignments WHERE person_id=? AND returned_date IS NULL LIMIT 1",
        (pid,),
    ).fetchone()
    return "EV" if r else "BIKE"


def process_cycle(company, cycle_start, cycle_end, file_bytes, *,
                  overrides=None, created_by="engine", commit=True) -> CycleResult:
    overrides = overrides or CycleOverrides()
    parsed = parse_file(company, file_bytes)
    holds = compute_holds(parsed)
    result = CycleResult(company=company, cycle_start=cycle_start, cycle_end=cycle_end,
                         warnings=list(parsed.warnings))

    conn = get_connection()
    try:
        persist_holds(conn, company, cycle_start, cycle_end, holds)

        present_persons = {}
        for rec in parsed.records:
            p = _lookup(conn, rec.rider_id, company)
            if p:
                present_persons[rec.rider_id] = p
            else:
                result.unknown_ids.append(rec.rider_id)
                result.warnings.append(f"Unknown rider_id '{rec.rider_id}' - skipped")
        present_rider_ids = set(present_persons)
        present_person_ids = {p["person_id"] for p in present_persons.values()}

        held_set = set(holds.held_rider_ids)
        for rid, ov in overrides.per_rider.items():
            if ov.force_hold: held_set.add(rid)
            if ov.force_release: held_set.discard(rid)
        held_person_ids = set()
        for rid in held_set:
            p = present_persons.get(rid) or _lookup(conn, rid, company)
            if p: held_person_ids.add(p["person_id"])

        # Cascade pre-pass
        anchors = conn.execute(
            "SELECT pr.person_id, pr.deduction_rider_id FROM person_registry pr "
            "JOIN ev_assignments ea ON ea.person_id=pr.person_id AND ea.returned_date IS NULL "
            "WHERE pr.deduction_company=?", (company,),
        ).fetchall()
        for a in anchors:
            ded = a["deduction_rider_id"]
            if ded in present_rider_ids: continue
            for cand_rid, cand_p in present_persons.items():
                if cand_p["person_id"] == a["person_id"]:
                    conn.execute(
                        "UPDATE person_registry SET deduction_rider_id=? WHERE person_id=?",
                        (cand_rid, a["person_id"]),
                    )
                    _txn(conn, person_id=a["person_id"], rider_id=cand_rid, company=company,
                         cycle_start=cycle_start, cycle_end=cycle_end,
                         event_type="DEDUCTION_SWITCH", amount=0.0,
                         balance_after=_balance(conn, a["person_id"]),
                         remarks=f"{ded} -> {cand_rid} (same company)", created_by=created_by)
                    result.warnings.append(f"Deduction anchor switched: {ded} -> {cand_rid}")
                    cand_p["deduction_rider_id"] = cand_rid
                    break

        # Main pass
        rent_done = set()
        for rec in parsed.records:
            person = present_persons.get(rec.rider_id)
            if not person: continue
            pid = person["person_id"]
            ov = overrides.per_rider.get(rec.rider_id, RiderOverride())

            # Rent is charged on the first qualifying cycle that processes
            # this person — regardless of which company that happens to be.
            # Double-charging is prevented by ev_assignments.rent_charged_through:
            # resolve_rent returns rent=0 once it's been advanced past the
            # current cycle_end, so any later company processing the same
            # cycle sees nothing left to charge. The deduction-company anchor
            # remains useful for arrears/dues attribution and as the fallback
            # logger in the absence pass below, but it no longer gates the
            # main rent charge. (Older behavior: gated on deduction_company,
            # which meant a late upload from the deduction company let rent
            # silently slip.)
            charge_here = pid not in rent_done
            if charge_here:
                rinfo = resolve_rent(conn, pid, cycle_start, cycle_end,
                                    waive_days=ov.waive_days, waive_all=ov.waive_all,
                                    rent_override=ov.rent_override)
                rent, rent_days = rinfo.rent, rinfo.days
                ev_id, model = rinfo.ev_id, rinfo.model
            else:
                rinfo = None; rent, rent_days = 0.0, 0
                ev_id, model = _ev_for(conn, pid)

            prev_bal = _balance(conn, pid)
            arr_out = _arrears_out(conn, pid)
            cod_amt_for_settle = holds.per_rider.get(rec.rider_id, 0.0)
            cod_carry = get_cod_arrears(conn, pid)[2]
            # Cross-company pending rent gets folded into THIS cycle's rent.
            pending_xc_before, pending_xc_origin = _get_pending_xc(conn, pid)
            effective_rent = rent + pending_xc_before
            s = apply_settlement(rec.payout, effective_rent, prev_bal, arr_out,
                                 cod_due=cod_amt_for_settle,
                                 cod_outstanding=cod_carry)

            _txn(conn, person_id=pid, rider_id=rec.rider_id, company=company,
                 cycle_start=cycle_start, cycle_end=cycle_end, event_type="PAYOUT",
                 amount=rec.payout, balance_after=prev_bal + rec.payout, created_by=created_by)
            if rent > 0:
                # RENT records ONLY this cycle's rent (not any folded-in pending
                # from a prior cycle). RENT_COLLECTED records the portion of the
                # rider's payout that went toward THIS cycle's rent. Any
                # additional money that landed against carried pending or
                # missed-rent arrears is logged separately as XC_RENT_RECOVERED
                # or RENT_RECOVERED so the EV Rent Details dashboard can show
                # both as "collected" without double-counting expected.
                rent_collected_this_cycle = min(s.rent_paid, rent)
                _txn(conn, person_id=pid, rider_id=rec.rider_id, company=company,
                     cycle_start=cycle_start, cycle_end=cycle_end, event_type="RENT",
                     amount=-rent, balance_after=prev_bal + rec.payout - rent,
                     days=rent_days, created_by=created_by)
                if rent_collected_this_cycle > 0:
                    _txn(conn, person_id=pid, rider_id=rec.rider_id, company=company,
                         cycle_start=cycle_start, cycle_end=cycle_end,
                         event_type="RENT_COLLECTED",
                         amount=rent_collected_this_cycle,
                         balance_after=prev_bal + rec.payout - rent + rent_collected_this_cycle,
                         days=rent_days, created_by=created_by,
                         remarks=("Rent fully collected from payout"
                                  if rent_collected_this_cycle >= rent
                                  else f"Partial rent collected; {rent - rent_collected_this_cycle:.2f} rolls to dues"))
            if s.arrears_recovered > 0:
                record_recovery(conn, pid, s.arrears_recovered, cycle_start, cycle_end,
                                rider_id=rec.rider_id, company=company, created_by=created_by)
            # COD is intentionally NOT recovered or missed via the payout — it's
            # just a HOLD marker. compute_holds already populated cod_holds for
            # this cycle, and is_hold (computed below) flags the rider in
            # the result so the operator can collect COD outside the payout.
            # Dues cleared this cycle (positive cash-flow toward closing prior debt).
            if s.dues_cleared > 0:
                _txn(conn, person_id=pid, rider_id=rec.rider_id, company=company,
                     cycle_start=cycle_start, cycle_end=cycle_end,
                     event_type="DUES_CLEARED",
                     amount=s.dues_cleared,
                     balance_after=prev_bal + rec.payout - rent + s.arrears_recovered + s.dues_cleared,
                     remarks="Prior dues recovered from payout", created_by=created_by)
            # Cash actually released to the rider closes the books for this cycle.
            if s.released > 0:
                _txn(conn, person_id=pid, rider_id=rec.rider_id, company=company,
                     cycle_start=cycle_start, cycle_end=cycle_end,
                     event_type="RELEASE",
                     amount=-s.released, balance_after=s.new_balance,
                     remarks="Net payout released to rider", created_by=created_by)
            # ── Cross-company rent re-routing ─────────────────────────────────
            # For multi-company riders, a first-attempt rent shortfall is moved
            # OUT of general dues into a separate "pending_xc_rent" bucket so
            # their next cycle at the other company gets the first crack at it.
            # A second-attempt failure (or absence at the other company, handled
            # in the absence pass) lets the shortfall fall through to ordinary
            # carryforward.
            rent_short_this_cycle = max(0.0, effective_rent - s.rent_paid)
            final_balance = s.new_balance
            new_pending_xc = pending_xc_before
            new_pending_origin = pending_xc_origin

            if rent_short_this_cycle > 0 and pending_xc_before == 0:
                # First-attempt path — only if the person is at 2+ companies.
                if _is_multi_company(conn, pid):
                    final_balance += rent_short_this_cycle   # un-debit from general dues
                    new_pending_xc = rent_short_this_cycle
                    new_pending_origin = company
                    _txn(conn, person_id=pid, rider_id=rec.rider_id, company=company,
                         cycle_start=cycle_start, cycle_end=cycle_end,
                         event_type="XC_RENT_PENDING",
                         amount=-rent_short_this_cycle, balance_after=final_balance,
                         remarks=("Partial rent held for recovery at other company"),
                         created_by=created_by)
            elif pending_xc_before > 0:
                # Second attempt: whatever didn't get recovered now becomes
                # ordinary carryforward — already in final_balance. Clear pending.
                new_pending_xc = 0.0
                new_pending_origin = None
                recovered_xc = pending_xc_before - rent_short_this_cycle
                if recovered_xc > 0:
                    _txn(conn, person_id=pid, rider_id=rec.rider_id, company=company,
                         cycle_start=cycle_start, cycle_end=cycle_end,
                         event_type="XC_RENT_RECOVERED",
                         amount=recovered_xc, balance_after=final_balance,
                         remarks=("Pending cross-company rent recovered"),
                         created_by=created_by)
                if rent_short_this_cycle > 0:
                    _txn(conn, person_id=pid, rider_id=rec.rider_id, company=company,
                         cycle_start=cycle_start, cycle_end=cycle_end,
                         event_type="XC_RENT_TO_CARRY",
                         amount=-rent_short_this_cycle, balance_after=final_balance,
                         remarks=("Pending rent converted to carryforward"),
                         created_by=created_by)

            # DUES_CARRY records what carries into the next cycle. Amount is the
            # *change* in the balance this cycle (negative = more dues added).
            balance_delta = final_balance - prev_bal
            if final_balance < 0 or balance_delta != 0:
                _txn(conn, person_id=pid, rider_id=rec.rider_id, company=company,
                     cycle_start=cycle_start, cycle_end=cycle_end, event_type="DUES_CARRY",
                     amount=balance_delta, balance_after=final_balance,
                     remarks=("Dues carried forward" if final_balance < 0 else "Balance settled"),
                     created_by=created_by)

            _set_balance(conn, pid, final_balance, cycle_end)
            _set_pending_xc(conn, pid, new_pending_xc, new_pending_origin)
            _mark_present(conn, pid, cycle_end)
            if charge_here and rinfo and rinfo.has_ev:
                advance_rent_charged_through(conn, pid, cycle_end)
                rent_done.add(pid)

            is_hold = pid in held_person_ids or rec.rider_id in held_set
            cod_amt = holds.per_rider.get(rec.rider_id, 0.0)

            rr = RiderResult(
                person_id=pid, rider_id=rec.rider_id, name=person["name"],
                hub=person["hub"], vehicle=person.get("vehicle"),
                company=company, ev_id=ev_id, model=model,
                payout=rec.payout, rent=rent, days=rent_days,
                arrears_recovered=s.arrears_recovered, dues_cleared=s.dues_cleared,
                prev_balance=prev_bal, released=s.released, new_balance=s.new_balance,
                new_arrears=s.new_arrears, cod_hold=cod_amt, is_hold=is_hold,
                remarks="HOLD" if is_hold else "PAY",
                account_no=person["account_no"], ifsc=person["ifsc"],
                orders=getattr(rec, "orders", None),
            )
            (result.pay_rows if s.released > 0 else result.dues_rows).append(rr)

        # Absence pass — only people who actually have an active rider_master
        # row in THIS company. (deduction_company is just a hint for where rent
        # gets logged; the company scope must come from rider_master directly,
        # otherwise the seed importer's alphabetical default contaminates the
        # INACTIVE sheet with riders from other companies.)
        total_missed = 0.0
        for a in conn.execute(
            "SELECT pr.person_id, pr.display_name, pr.deduction_rider_id "
            "FROM person_registry pr "
            "JOIN ev_assignments ea ON ea.person_id=pr.person_id AND ea.returned_date IS NULL "
            "WHERE EXISTS ("
            "    SELECT 1 FROM rider_master rm "
            "    WHERE rm.person_id = pr.person_id AND rm.company = ? AND rm.is_active = 1"
            ")", (company,),
        ).fetchall():
            pid = a["person_id"]
            if pid in present_person_ids: continue
            rinfo = resolve_rent(conn, pid, cycle_start, cycle_end)
            # If this person had pending cross-company rent originating elsewhere,
            # and they're now absent at the "other company" cycle: convert the
            # pending bucket to general carryforward, then clear it.
            pending_xc_before, pending_xc_origin = _get_pending_xc(conn, pid)
            if pending_xc_before > 0 and pending_xc_origin != company:
                cur_bal = _balance(conn, pid)
                new_bal = cur_bal - pending_xc_before
                _txn(conn, person_id=pid, rider_id=a["deduction_rider_id"] or "",
                     company=company, cycle_start=cycle_start, cycle_end=cycle_end,
                     event_type="XC_RENT_TO_CARRY",
                     amount=-pending_xc_before, balance_after=new_bal,
                     remarks="Absent at other company; pending rent → carryforward",
                     created_by=created_by)
                _set_balance(conn, pid, new_bal, cycle_end)
                _set_pending_xc(conn, pid, 0.0, None)
            if rinfo.has_ev and rinfo.rent > 0:
                record_missed_rent(conn, pid, rinfo.rent, cycle_start, cycle_end,
                                   rider_id=a["deduction_rider_id"] or "",
                                   company=company, created_by=created_by, days=rinfo.days)
                advance_rent_charged_through(conn, pid, cycle_end)
                total_missed += rinfo.rent
            ridx_rows = conn.execute(
                "SELECT rider_id, hub FROM rider_master WHERE person_id=? AND company=?",
                (pid, company)).fetchall()
            ridx = [r["rider_id"] for r in ridx_rows]
            hub = next((r["hub"] for r in ridx_rows if r["hub"]), None)
            cur = _balance(conn, pid); arr = _arrears_out(conn, pid)
            veh = _vehicle_for(conn, pid, company)
            reasons = []
            if rinfo.rent > 0: reasons.append(f"Missed rent {rinfo.rent:.0f}")
            if cur < 0:       reasons.append(f"Dues {-cur:.0f}")
            if arr > 0:       reasons.append(f"Arrears {arr:.0f}")
            result.inactive_rows.append(InactiveRider(
                person_id=pid, name=a["display_name"], rider_ids=ridx, vehicle=veh,
                hub=hub, ev_id=rinfo.ev_id, model=rinfo.model, current_balance=cur,
                arrears_outstanding=arr, reason="; ".join(reasons) if reasons else "Absent"))

        for adj in overrides.adjustments:
            pid = adj.get("person_id")
            if not pid and adj.get("rider_id"):
                p = _lookup(conn, adj["rider_id"], company)
                if p: pid = p["person_id"]
            if pid and adj.get("amount") and adj.get("reason"):
                post_adjustment(conn, pid, adj["amount"], adj["reason"], created_by,
                                rider_id=adj.get("rider_id", ""), company=company)

        result.hold_rows = [{"rider_id": rid, "amount": amt}
                            for rid, amt in sorted(holds.per_rider.items(), key=lambda x: -x[1])]
        all_rows = result.pay_rows + result.dues_rows
        result.totals = {
            "riders_paid": len(result.pay_rows),
            "riders_in_dues": len(result.dues_rows),
            "total_release": round(sum(r.released for r in result.pay_rows), 2),
            "total_rent_charged": round(sum(r.rent for r in all_rows), 2),
            "total_arrears_recovered": round(sum(r.arrears_recovered for r in all_rows), 2),
            "rent_missed_this_cycle": round(total_missed, 2),
            "total_cod_held": round(sum(r.cod_hold for r in all_rows if r.is_hold), 2),
            "held_count": sum(1 for r in all_rows if r.is_hold),
            "inactive_count": len(result.inactive_rows),
        }
        result.committed = commit
        if commit: conn.commit()
        else: conn.rollback()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
    return result
