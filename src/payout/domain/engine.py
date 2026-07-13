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
from payout.domain.ev_daily import (
    attribute_recovery as _ev_attribute_recovery,
    materialize_cycle_for_person as _ev_materialize_cycle,
)
from payout.domain.holds import compute_holds, persist_holds
from payout.domain.rent import advance_rent_charged_through, resolve_rent
from payout.parsers import parse_file
from payout.money import to_rupees


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
    # Each entry: {rider_id, name, hub, payout} — for the onboarding modal.
    unknown_riders: list = field(default_factory=list)
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
    """Return (amount, origin_company, origin_cycle_end) of the pending cross-
    company rent bucket. (0.0, None, None) if there's nothing pending."""
    r = conn.execute(
        "SELECT pending_xc_rent, xc_origin_company, xc_origin_cycle_end "
        "FROM balances WHERE person_id=?", (pid,),
    ).fetchone()
    if not r:
        return (0.0, None, None)
    return (
        float(r["pending_xc_rent"] or 0),
        r["xc_origin_company"],
        r["xc_origin_cycle_end"],
    )


def _set_pending_xc(conn, pid, amount, origin_company, origin_cycle_end=None):
    conn.execute(
        "INSERT INTO balances (person_id, current_balance, pending_xc_rent, "
        "xc_origin_company, xc_origin_cycle_end, last_updated) "
        "VALUES (?, 0, ?, ?, ?, date('now')) "
        "ON CONFLICT(person_id) DO UPDATE SET "
        "  pending_xc_rent=excluded.pending_xc_rent, "
        "  xc_origin_company=excluded.xc_origin_company, "
        "  xc_origin_cycle_end=excluded.xc_origin_cycle_end, "
        "  last_updated=excluded.last_updated",
        (pid, amount, origin_company, origin_cycle_end),
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
                result.unknown_riders.append({
                    "rider_id": rec.rider_id,
                    "name": rec.name or "",
                    "hub":  rec.hub  or "",
                    "payout": rec.payout,
                })
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
                # Soft cap: a catch-up window longer than 21 days almost
                # always means a previous cycle was skipped or someone joined
                # late and missed updates. Flag for manual review but bill it.
                if rent_days > 21:
                    result.warnings.append(
                        f"Catch-up window for person_id={pid} "
                        f"({rec.rider_id}@{company}) is {rent_days} days "
                        f"(~{to_rupees(rent):,.0f}). Likely a missed prior cycle or "
                        f"late-onboarded rider — review before commit."
                    )
            else:
                rinfo = None; rent, rent_days = 0.0, 0
                ev_id, model = _ev_for(conn, pid)

            prev_bal = _balance(conn, pid)
            arr_out = _arrears_out(conn, pid)
            cod_amt_for_settle = holds.per_rider.get(rec.rider_id, 0.0)
            cod_carry = get_cod_arrears(conn, pid)[2]
            # Cross-company pending rent gets folded into THIS cycle's rent.
            pending_xc_before, pending_xc_origin, pending_xc_cycle_end = \
                _get_pending_xc(conn, pid)
            # NEW-CYCLE COLLAPSE: if we're charging fresh rent for a strictly
            # later cycle than the pending bucket's origin, the prior cycle is
            # done with — whatever didn't get recovered cross-company over the
            # past week collapses into general carryforward dues right now,
            # then we proceed with this cycle's rent untainted.
            if (charge_here and rent > 0 and pending_xc_before > 0
                    and pending_xc_cycle_end
                    and pending_xc_cycle_end < _iso(cycle_start)):
                new_bal_after_collapse = prev_bal - pending_xc_before
                _txn(conn, person_id=pid, rider_id=rec.rider_id, company=company,
                     cycle_start=cycle_start, cycle_end=cycle_end,
                     event_type="XC_RENT_TO_CARRY",
                     amount=-pending_xc_before, balance_after=new_bal_after_collapse,
                     remarks=(f"Prior cycle's pending rent ({pending_xc_origin}, "
                              f"end {pending_xc_cycle_end}) collapsed to dues at "
                              f"start of new cycle"),
                     created_by=created_by)
                _set_balance(conn, pid, new_bal_after_collapse, cycle_end)
                _set_pending_xc(conn, pid, 0.0, None, None)
                prev_bal = new_bal_after_collapse
                pending_xc_before = 0.0
                pending_xc_origin = None
                pending_xc_cycle_end = None
            effective_rent = rent + pending_xc_before
            s = apply_settlement(rec.payout, effective_rent, prev_bal, arr_out,
                                 cod_due=cod_amt_for_settle,
                                 cod_outstanding=cod_carry)

            _txn(conn, person_id=pid, rider_id=rec.rider_id, company=company,
                 cycle_start=cycle_start, cycle_end=cycle_end, event_type="PAYOUT",
                 amount=rec.payout, balance_after=prev_bal + rec.payout, created_by=created_by)
            if rent > 0:
                # Guardrail: with a correctly-advanced meter, RENT never covers
                # more days than the cycle spans. rent_days > span means the
                # meter was behind at cycle start (a stuck-meter catch-up); if
                # arrears are ALSO recovered this run, the catch-up may re-bill
                # the very days being clawed back -> a double-charge. Flag it so
                # the operator reviews before committing.
                _span = (date.fromisoformat(_iso(cycle_end))
                         - date.fromisoformat(_iso(cycle_start))).days + 1
                if rent_days and rent_days > _span and s.arrears_recovered > 0:
                    result.warnings.append(
                        f"person_id={pid} ({rec.rider_id}@{company}): RENT bills "
                        f"{rent_days} days for a {_span}-day cycle while arrears "
                        f"were recovered this run - possible double-charge from a "
                        f"stuck meter. Review before commit "
                        f"(scripts/find_spencers_double_charge.py)."
                    )
                # RENT records ONLY this cycle's rent (not any folded-in pending
                # from a prior cycle). RENT_COLLECTED records the portion of the
                # rider's payout that went toward THIS cycle's rent. Any
                # additional money that landed against carried pending or
                # missed-rent arrears is logged separately as XC_RENT_RECOVERED
                # or RENT_RECOVERED so the EV Rent Details dashboard can show
                # both as "collected" without double-counting expected.
                rent_collected_this_cycle = min(s.rent_paid, rent)
                # Multi-leg breakdown in the remarks: useful when an EV was
                # swapped mid-cycle so the audit trail shows which EV's days
                # contributed. Empty remarks (default "") when there's only
                # one leg.
                rent_remarks = ""
                legs = getattr(rinfo, "legs", []) or []
                billed_legs = [
                    L for L in legs if (L.days or 0) > 0 or (L.rent or 0) > 0
                ]
                if len(billed_legs) > 1:
                    rent_remarks = " + ".join(
                        f"{L.ev_id} {L.days}d ({to_rupees(L.rent):,.2f})"
                        for L in billed_legs
                    )
                rent_txn_id = conn.execute(
                    "INSERT INTO transactions (person_id, rider_id, company, "
                    "cycle_start, cycle_end, event_type, amount, balance_after, "
                    "days, remarks, created_by) "
                    "VALUES (?,?,?,?,?,'RENT',?,?,?,?,?)",
                    (pid, rec.rider_id, company,
                     _iso(cycle_start), _iso(cycle_end),
                     -rent, prev_bal + rec.payout - rent,
                     rent_days, rent_remarks, created_by),
                ).lastrowid
                # Day-level ledger: write 'billed' rows for every day each leg
                # contributed. Lets the weekly Raft reconciliation derive
                # missed-vs-collected for any calendar window.
                _ev_materialize_cycle(
                    conn, person_id=pid,
                    cycle_start=cycle_start, cycle_end=cycle_end,
                    legs=billed_legs, billing_event_id=rent_txn_id,
                    billing_status="billed",
                )
                if rent_collected_this_cycle > 0:
                    _txn(conn, person_id=pid, rider_id=rec.rider_id, company=company,
                         cycle_start=cycle_start, cycle_end=cycle_end,
                         event_type="RENT_COLLECTED",
                         amount=rent_collected_this_cycle,
                         balance_after=prev_bal + rec.payout - rent + rent_collected_this_cycle,
                         days=rent_days, created_by=created_by,
                         remarks=("Rent fully collected from payout"
                                  if rent_collected_this_cycle >= rent
                                  else f"Partial rent collected; {to_rupees(rent - rent_collected_this_cycle):,.2f} rolls to dues"))
            if s.arrears_recovered > 0:
                record_recovery(conn, pid, s.arrears_recovered, cycle_start, cycle_end,
                                rider_id=rec.rider_id, company=company, created_by=created_by)
                # Heal the oldest 'missed' day-rows for this person up to the
                # recovered amount, so the weekly Raft report knows which past
                # week's miss has now been clawed back.
                recovery_id = conn.execute(
                    "SELECT id FROM transactions WHERE person_id=? "
                    "AND event_type='RENT_RECOVERED' "
                    "AND cycle_start=? AND cycle_end=? "
                    "ORDER BY id DESC LIMIT 1",
                    (pid, _iso(cycle_start), _iso(cycle_end))
                ).fetchone()
                if recovery_id:
                    _ev_attribute_recovery(
                        conn, person_id=pid,
                        recovery_event_id=recovery_id["id"],
                        amount=s.arrears_recovered,
                    )
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
            # Behavior:
            #   * First-attempt path — fresh shortfall opens pending_xc.
            #   * Subsequent attempts — recover what we can; KEEP the rest
            #     alive (don't collapse to dues). The new-cycle collapse at the
            #     top of the loop handles the "give up" case when a strictly
            #     later cycle's rent arrives.
            rent_short_this_cycle = max(0.0, effective_rent - s.rent_paid)
            final_balance = s.new_balance
            new_pending_xc = pending_xc_before
            new_pending_origin = pending_xc_origin
            new_pending_cycle_end = pending_xc_cycle_end

            if rent_short_this_cycle > 0 and pending_xc_before == 0:
                # First-attempt path — only if the person is at 2+ companies.
                if _is_multi_company(conn, pid):
                    final_balance += rent_short_this_cycle   # un-debit from general dues
                    new_pending_xc = rent_short_this_cycle
                    new_pending_origin = company
                    new_pending_cycle_end = _iso(cycle_end)
                    _txn(conn, person_id=pid, rider_id=rec.rider_id, company=company,
                         cycle_start=cycle_start, cycle_end=cycle_end,
                         event_type="XC_RENT_PENDING",
                         amount=-rent_short_this_cycle, balance_after=final_balance,
                         remarks=("Partial rent held for recovery at other company"),
                         created_by=created_by)
            elif pending_xc_before > 0:
                # Subsequent attempt within the same cycle window. Split the
                # apply_settlement's rent_paid between current rent and the
                # pending bucket (current paid first): anything beyond
                # current rent goes against pending.
                pending_paid = max(0.0, s.rent_paid - rent)
                pending_remaining = max(0.0, pending_xc_before - pending_paid)
                recovered_xc = pending_xc_before - pending_remaining
                # apply_settlement treated pending as part of THIS cycle's
                # rent; un-debit whatever's still unrecovered so it stays in
                # the pending bucket rather than current_balance.
                final_balance += pending_remaining
                new_pending_xc = pending_remaining
                new_pending_origin = pending_xc_origin if pending_remaining > 0 else None
                new_pending_cycle_end = pending_xc_cycle_end if pending_remaining > 0 else None
                if recovered_xc > 0:
                    xc_id = conn.execute(
                        "INSERT INTO transactions (person_id, rider_id, company, "
                        "cycle_start, cycle_end, event_type, amount, "
                        "balance_after, remarks, created_by) "
                        "VALUES (?,?,?,?,?,'XC_RENT_RECOVERED',?,?,?,?)",
                        (pid, rec.rider_id, company,
                         _iso(cycle_start), _iso(cycle_end),
                         recovered_xc, final_balance,
                         "Pending cross-company rent recovered", created_by),
                    ).lastrowid
                    # Heal day-rows for the missed days this XC recovery
                    # actually pays down.
                    _ev_attribute_recovery(
                        conn, person_id=pid,
                        recovery_event_id=xc_id, amount=recovered_xc,
                    )
                # NOTE: no XC_RENT_TO_CARRY here anymore. The remainder stays
                # alive in pending_xc_rent and gets another shot at the next
                # company's run. Only the new-cycle collapse at the top of the
                # loop (when a strictly later cycle's RENT arrives) finally
                # writes it off to general carryforward dues.

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
            _set_pending_xc(conn, pid, new_pending_xc, new_pending_origin,
                            new_pending_cycle_end)
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
            # NOTE: absence alone no longer collapses a pending_xc_rent bucket.
            # Under the new model, pending stays alive across every company
            # run in the cycle window — it only falls to general carryforward
            # when a strictly later cycle's RENT lands (handled at the top of
            # the present-rider loop above).
            if rinfo.has_ev and rinfo.rent > 0:
                record_missed_rent(conn, pid, rinfo.rent, cycle_start, cycle_end,
                                   rider_id=a["deduction_rider_id"] or "",
                                   company=company, created_by=created_by, days=rinfo.days)
                # Find the RENT_MISSED transaction we just wrote so we can
                # attribute the missed days back to it in the daily ledger.
                missed_id = conn.execute(
                    "SELECT id FROM transactions WHERE person_id=? "
                    "AND event_type='RENT_MISSED' AND company=? "
                    "AND cycle_start=? AND cycle_end=? "
                    "ORDER BY id DESC LIMIT 1",
                    (pid, company, _iso(cycle_start), _iso(cycle_end))
                ).fetchone()
                billed_legs = [L for L in (rinfo.legs or []) if (L.days or 0) > 0]
                _ev_materialize_cycle(
                    conn, person_id=pid,
                    cycle_start=cycle_start, cycle_end=cycle_end,
                    legs=billed_legs,
                    billing_event_id=(missed_id["id"] if missed_id else None),
                    billing_status="missed",
                )
                # Advance the meter past the missed window. The missed days
                # now live solely in EV arrears (clawed back later as cash).
                # Leaving the meter behind made the next overlapping cycle
                # re-bill those same days via a catch-up RENT *while* the
                # arrears were also recovered -- double-charging the rider.
                # Advancing here keeps every EV day billed exactly once.
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
            if rinfo.rent > 0: reasons.append(f"Missed rent {to_rupees(rinfo.rent):,.0f}")
            if cur < 0:       reasons.append(f"Dues {to_rupees(-cur):,.0f}")
            if arr > 0:       reasons.append(f"Arrears {to_rupees(arr):,.0f}")
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
        if commit:
            # Cycle tracking: write a company_cycles row so dashboards have a
            # cheap join target instead of recomputing from the transactions
            # table. week_bucket groups the four companies' runs that fall in
            # the same ISO week (Mon-Sun, derived from cycle_end) into a
            # "global cycle" for cross-company dashboards.
            from datetime import date as _date_cls
            ce_d = (cycle_end if isinstance(cycle_end, _date_cls)
                    else _date_cls.fromisoformat(_iso(cycle_end)))
            iso_year, iso_week, _ = ce_d.isocalendar()
            week_bucket = f"{iso_year}-W{iso_week:02d}"
            t = result.totals
            total_rent_collected = round(
                sum(
                    min(r.rent, r.rent - (max(0.0, -r.new_balance) if r.is_hold else 0.0))
                    for r in result.pay_rows
                    if getattr(r, "rent", 0) > 0
                ),
                2,
            )
            conn.execute(
                "INSERT INTO company_cycles "
                "(company, cycle_start, cycle_end, week_bucket, "
                " processed_by, rider_count, riders_paid, riders_in_dues, "
                " total_release, total_rent_charged, total_rent_collected, "
                " total_rent_missed) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(company, cycle_start, cycle_end) DO UPDATE SET "
                "  week_bucket=excluded.week_bucket, "
                "  processed_at=datetime('now'), "
                "  processed_by=excluded.processed_by, "
                "  rider_count=excluded.rider_count, "
                "  riders_paid=excluded.riders_paid, "
                "  riders_in_dues=excluded.riders_in_dues, "
                "  total_release=excluded.total_release, "
                "  total_rent_charged=excluded.total_rent_charged, "
                "  total_rent_collected=excluded.total_rent_collected, "
                "  total_rent_missed=excluded.total_rent_missed",
                (company, _iso(cycle_start), _iso(cycle_end), week_bucket,
                 created_by,
                 t["riders_paid"] + t["riders_in_dues"],
                 t["riders_paid"], t["riders_in_dues"],
                 t["total_release"], t["total_rent_charged"],
                 total_rent_collected, t["rent_missed_this_cycle"]),
            )
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        conn.rollback(); raise
    finally:
        conn.close()
    return result
