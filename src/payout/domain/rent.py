"""EV rent calculation.

Rent is a continuous daily meter. Each cycle bills its own days — from the
day after ``rent_charged_through`` (the last date already billed) up to the
cycle end — and the meter advances whether a day was charged (rider present)
or missed to arrears (absent).

Gap catch-up (2026-09-04, the Jeet Ghosh case): a rider present at Spencer's
15–21 (meter → 21) and then at Myntra 24–30 was billed 7 days by Myntra and
the meter jumped to 30, so 22–23 were never billed by anyone — Spencer's
22–31 then found the meter at 30 and billed only the 31st. Days behind the
meter that no rent event ever accounted for are now billed by the next cycle
that processes the rider (see ``unbilled_gap``): the walk back from
``cycle_start - 1`` stops at the first day that IS accounted for — a
day-ledger row with a billing status, or (where the day-ledger predates the
row) a RENT / RENT_MISSED window — so the stuck-meter double charge the old
"no reach-back" rule guarded against still cannot happen.

Multi-assignment handling: a rider can swap EVs mid-cycle (return one, take
another the same day). For a given (person, cycle) we sum rent across every
assignment that overlapped the cycle, with each assignment's window clamped to
``[handover_date + 1 .. returned_date - 1]`` (handover day and return day are
free). The old "look at the open assignment only" rule silently dropped the
returned EV's days.

Pure helpers (chargeable_window, chargeable_days, rent_for_days) plus
resolve_rent which sums across overlapping assignments, applies maintenance
windows and manual overrides. advance_rent_charged_through advances the meter
on every assignment that participated in a cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from payout.config import STANDARD_CYCLE_DAYS


@dataclass
class AssignmentLeg:
    """One assignment's contribution to a cycle's rent."""

    assignment_id: int
    ev_id: str
    provider: str
    model: str
    weekly_rate: float
    handover_date: date | None
    returned_date: date | None
    rent_charged_through: date | None
    days: int  # chargeable after maintenance & waiver
    base_days: int  # before maintenance / waiver
    maintenance_days: int
    rent: float
    rent_from: date | None
    rent_through: date | None
    # Days before cycle_start that were behind the meter and unaccounted for,
    # billed by this cycle (see unbilled_gap). 0 in the normal case.
    catchup_days: int = 0


@dataclass
class RentInfo:
    has_ev: bool
    ev_id: str | None  # display: open assignment if any, else most recent returned
    provider: str | None
    model: str | None
    weekly_rate: float
    handover_date: date | None
    days: int  # total across legs
    rent: float  # total across legs
    base_days: int = 0
    maintenance_days: int = 0
    waived_days: int = 0
    rent_from: date | None = None
    charged_through: date | None = None
    legs: list[AssignmentLeg] = field(default_factory=list)
    catchup_days: int = 0  # total across legs
    # Unaccounted days further back than the contiguous catch-up run (an
    # accounted day sits between them and the cycle). Never billed here —
    # surfaced as a warning for the back-rent flow.
    orphan_gap_days: int = 0


def chargeable_window(
    cycle_start, cycle_end, handover_date, charged_through=None, returned_date=None
):
    """Inclusive ``(start, end)`` chargeable range for a single assignment, or
    ``None`` if zero days.

    Billing model:
      * ``start = max(charged_through + 1, cycle_start)`` — this helper
        charges the cycle's own days. A meter behind ``cycle_start`` is
        handled separately by ``resolve_rent`` via ``unbilled_gap``, which
        reaches back only over days no rent event ever accounted for (so
        the stuck-meter double charge cannot recur). A brand-new assignment
        with a backdated handover and NO meter still does not reach back:
        those days go through the manual back-rent flow.
      * Brand-new assignment with no meter: ``handover_date + 1`` when
        handover lands mid-cycle; else ``cycle_start``.
      * Return day is free: ``end = min(cycle_end, returned_date - 1)``.
    """
    if charged_through is not None:
        start = charged_through + timedelta(days=1)
    elif handover_date is not None and handover_date >= cycle_start:
        # Handover day is free whether handover lands mid-cycle (> cycle_start)
        # OR exactly on cycle_start. Without the >= the engine would charge for
        # cycle_start while the daily ledger marks it 'handover_free', so the
        # two views disagree by one day. Aligning them keeps Provider Weekly's
        # "expected vs collected" reconciliation clean.
        start = handover_date + timedelta(days=1)
    else:
        start = cycle_start
    # A cycle only ever bills its OWN days: never reach before cycle_start.
    # A behind meter (backdated handover, stray data, etc.) does NOT catch up
    # here — that reach-back is exactly what caused the stuck-meter double
    # charges. Backdated handovers' earlier un-billed days are captured once as
    # back-rent EV arrears via the manual back-rent flow instead.
    if start < cycle_start:
        start = cycle_start
    end = cycle_end
    if returned_date is not None:
        end = min(end, returned_date - timedelta(days=1))
    if start > end:
        return None
    return (start, end)


def chargeable_days(
    cycle_start, cycle_end, handover_date, charged_through=None, returned_date=None
):
    window = chargeable_window(
        cycle_start, cycle_end, handover_date, charged_through, returned_date
    )
    return 0 if window is None else (window[1] - window[0]).days + 1


def rent_for_days(weekly_rate, days):
    """Rent for ``days`` of a weekly rate, in integer paise (rounded once)."""
    from payout.money import prorate

    return prorate(int(weekly_rate), days, STANDARD_CYCLE_DAYS)


def maintenance_days_in_window(conn, ev_id, win_start, win_end):
    """Count cycle days the EV was in maintenance.

    A row with ``to_date IS NULL`` means the EV is still in maintenance (no
    return date logged yet) — for cycle billing we treat it as blocked all
    the way through ``win_end``.
    """
    rows = conn.execute(
        "SELECT from_date, to_date FROM ev_maintenance WHERE ev_id=?", (ev_id,)
    ).fetchall()
    blocked = set()
    for r in rows:
        lo = max(date.fromisoformat(r["from_date"]), win_start)
        if r["to_date"]:  # noqa: SIM108
            hi = min(date.fromisoformat(r["to_date"]), win_end)
        else:
            hi = win_end
        day = lo
        while day <= hi:
            blocked.add(day)
            day += timedelta(days=1)
    return len(blocked)


def _parse_date(s):
    return date.fromisoformat(s) if s else None


_GAP_LOOKBACK_DAYS = 7  # one cycle: older gaps are a human decision, not a surprise


def _day_accounted(conn, person_id, ev_id, day) -> bool:
    """Has this EV-day already been billed, missed to arrears, paid by hand,
    or otherwise settled? The day-ledger answers first: a row with a billing
    status, a free state, or another rider's name on it means yes. A row
    without a status (or no row at all) is not proof of an unbilled day —
    manual rent payments left such rows behind — so the person's rent
    transactions are consulted next. A rent row with a ``days`` count covers
    the last ``days`` days of its cycle window (a cycle that billed one day
    of a ten-day window covers only that day); a row without one (a manual
    rent payment, a reversal) covers its whole window. Maintenance days are
    never owed."""
    row = conn.execute(
        "SELECT billing_status, state, assigned_person_id FROM ev_daily_ledger "
        "WHERE ev_id=? AND day=?",
        (ev_id, day.isoformat()),
    ).fetchone()
    if row is not None:
        if row["assigned_person_id"] not in (None, person_id):
            return True  # the EV was someone else's that day
        if row["state"] in ("maintenance", "handover_free", "return_free", "unassigned"):
            return True  # a free day is not owed
        if row["billing_status"] is not None:
            return True
    # The window a rent row really billed: its last ``days`` days, counted
    # back from the cycle end or, for a unit returned mid-cycle, from the day
    # before the return (the last chargeable day). Old catch-up rows can carry
    # more days than their cycle window, so look at rows ending up to 60 days
    # after this day rather than only rows whose window contains it.
    iso = day.isoformat()
    ret = conn.execute(
        "SELECT returned_date FROM ev_assignments WHERE person_id=? AND ev_id=? "
        "AND (handover_date IS NULL OR handover_date <= ?) "
        "AND (returned_date IS NULL OR returned_date > ?) "
        "ORDER BY assignment_id DESC LIMIT 1",
        (person_id, ev_id, iso, iso),
    ).fetchone()
    ret_day = _parse_date(ret["returned_date"]) if ret and ret["returned_date"] else None
    for t in conn.execute(
        "SELECT event_type, cycle_start, cycle_end, days FROM transactions WHERE person_id=? "
        "AND event_type IN ('RENT','RENT_MISSED','RENT_COLLECTED','RENT_REVERSAL','RENT_WAIVED') "
        "AND cycle_end>=? AND cycle_end<=?",
        (person_id, iso, (day + timedelta(days=60)).isoformat()),
    ):
        c_start = _parse_date(str(t["cycle_start"])[:10])
        c_end = _parse_date(str(t["cycle_end"])[:10])
        n = t["days"]
        if n and t["event_type"] != "RENT_REVERSAL":
            last = c_end if ret_day is None else min(c_end, ret_day - timedelta(days=1))
            lo = last - timedelta(days=int(n) - 1)
        else:
            lo = c_start
        if lo <= day <= c_end:
            return True
    return maintenance_days_in_window(conn, ev_id, day, day) > 0


def unbilled_gap(conn, person_id, ev_id, gap_lo, gap_hi):
    """Days in ``[gap_lo, gap_hi]`` (the stretch between the meter and the
    cycle) that nothing ever billed. Returns ``(catchup_start, orphan_days)``:
    ``catchup_start`` is the first day of the contiguous unaccounted run that
    ends at ``gap_hi`` (None when ``gap_hi`` itself is accounted for), and
    ``orphan_days`` counts unaccounted days further back, behind an accounted
    day, which are NOT caught up here."""
    if gap_lo is None or gap_hi is None or gap_lo > gap_hi:
        return None, 0
    lo = max(gap_lo, gap_hi - timedelta(days=_GAP_LOOKBACK_DAYS))
    catchup_start = None
    orphans = 0
    day = gap_hi
    contiguous = True
    while day >= lo:
        if _day_accounted(conn, person_id, ev_id, day):
            contiguous = False
        elif contiguous:
            catchup_start = day
        else:
            orphans += 1
        day -= timedelta(days=1)
    return catchup_start, orphans


def resolve_rent(
    conn, person_id, cycle_start, cycle_end, *, waive_days=0, waive_all=False, rent_override=None
):
    """Sum rent across every assignment that overlapped the cycle.

    Overlap rule: handover_date <= cycle_end AND
                  (returned_date IS NULL OR returned_date >= cycle_start)
    Each assignment's chargeable window is clamped to its handover/return
    dates and then to the cycle. Maintenance and waiver days reduce the
    chargeable count per leg uniformly.

    ``rent_override`` (when supplied) replaces the engine-computed total —
    it's a flat override, not a per-leg one. ``waive_all`` zeroes the total.
    ``waive_days`` reduces the *total* base days (applied to the longest leg
    first; if it exceeds the longest leg it spills over to the next).
    """
    rows = conn.execute(
        """
        SELECT a.assignment_id, a.person_id, a.ev_id, a.handover_date, a.returned_date,
               a.rent_charged_through, m.provider, m.model_name, m.weekly_rate
        FROM ev_assignments a
        JOIN ev_units  u ON u.ev_id = a.ev_id
        JOIN ev_models m ON m.model_id = u.model_id
        WHERE a.person_id = ?
          AND (a.returned_date IS NULL OR a.returned_date >= ?)
          AND (a.handover_date IS NULL OR a.handover_date <= ?)
        ORDER BY COALESCE(a.handover_date, a.created_at) ASC
        """,
        (
            person_id,
            cycle_start.isoformat() if hasattr(cycle_start, "isoformat") else str(cycle_start),
            cycle_end.isoformat() if hasattr(cycle_end, "isoformat") else str(cycle_end),
        ),
    ).fetchall()

    if not rows:
        return RentInfo(False, None, None, None, 0.0, None, 0, 0.0)

    # Build per-leg chargeable windows.
    legs_data = []
    for r in rows:
        hod = _parse_date(r["handover_date"])
        ret = _parse_date(r["returned_date"])
        charged = _parse_date(r["rent_charged_through"])
        win = chargeable_window(cycle_start, cycle_end, hod, charged, ret)
        # Gap catch-up: the meter sits behind cycle_start and the days in
        # between were never accounted for by any cycle (see module doc).
        catchup_days = 0
        orphans = 0
        if charged is not None and charged + timedelta(days=1) < cycle_start:
            gap_lo = charged + timedelta(days=1)
            if hod is not None:
                gap_lo = max(gap_lo, hod + timedelta(days=1))
            gap_hi = cycle_start - timedelta(days=1)
            if ret is not None:
                gap_hi = min(gap_hi, ret - timedelta(days=1))
            catch_from, orphans = unbilled_gap(conn, r["person_id"], r["ev_id"], gap_lo, gap_hi)
            if catch_from is not None:
                catchup_days = (gap_hi - catch_from).days + 1
                win = (catch_from, gap_hi) if win is None else (catch_from, win[1])
        if win is None:
            base = maint = 0
            rfrom = rthrough = None
        else:
            rfrom, rthrough = win
            base = (rthrough - rfrom).days + 1
            maint = maintenance_days_in_window(conn, r["ev_id"], rfrom, rthrough)
        legs_data.append(
            {
                "row": r,
                "hod": hod,
                "ret": ret,
                "charged": charged,
                "rent_from": rfrom,
                "rent_through": rthrough,
                "base": base,
                "maint": maint,
                "catchup": catchup_days,
                "orphans": orphans,
            }
        )

    # Apply the waive_days budget across legs (largest leg first).
    waive_left = max(0, int(waive_days or 0))
    for leg in sorted(legs_data, key=lambda x: -x["base"]):
        eff = max(0, leg["base"] - leg["maint"])
        if waive_left <= 0:
            leg["waived"] = 0
        elif eff >= waive_left:
            leg["waived"] = waive_left
            waive_left = 0
        else:
            leg["waived"] = eff
            waive_left -= eff
    for leg in legs_data:
        leg.setdefault("waived", 0)

    built_legs: list[AssignmentLeg] = []
    total_base = total_maint = total_waived = total_days = 0
    total_catchup = total_orphans = 0
    total_rent = 0
    rent_from_overall: date | None = None
    rent_through_overall: date | None = None
    open_leg = None
    most_recent_returned = None

    for leg in legs_data:
        r = leg["row"]
        eff_days = max(0, leg["base"] - leg["maint"] - leg["waived"])
        leg_rent = rent_for_days(r["weekly_rate"], eff_days)
        built = AssignmentLeg(
            assignment_id=r["assignment_id"],
            ev_id=r["ev_id"],
            provider=r["provider"],
            model=r["model_name"],
            weekly_rate=int(r["weekly_rate"]),
            handover_date=leg["hod"],
            returned_date=leg["ret"],
            rent_charged_through=leg["charged"],
            days=eff_days,
            base_days=leg["base"],
            maintenance_days=leg["maint"],
            rent=leg_rent,
            rent_from=leg["rent_from"],
            rent_through=leg["rent_through"],
            catchup_days=leg["catchup"],
        )
        built_legs.append(built)
        total_days += eff_days
        total_catchup += leg["catchup"]
        total_orphans += leg["orphans"]
        total_base += leg["base"]
        total_maint += leg["maint"]
        total_waived += leg["waived"]
        total_rent += leg_rent
        if leg["rent_from"]:
            rent_from_overall = (
                leg["rent_from"]
                if rent_from_overall is None
                else min(rent_from_overall, leg["rent_from"])
            )
        if leg["rent_through"]:
            rent_through_overall = (
                leg["rent_through"]
                if rent_through_overall is None
                else max(rent_through_overall, leg["rent_through"])
            )
        if leg["ret"] is None and open_leg is None:
            open_leg = built
        elif leg["ret"] is not None:  # noqa: SIM102
            if most_recent_returned is None or (
                leg["ret"]
                and most_recent_returned.returned_date
                and leg["ret"] > most_recent_returned.returned_date
            ):
                most_recent_returned = built

    # Overrides apply to the TOTAL.
    if rent_override is not None:
        total_rent = int(rent_override)
    elif waive_all:
        total_rent = 0

    display = open_leg or most_recent_returned or built_legs[0]
    return RentInfo(
        has_ev=True,
        ev_id=display.ev_id,
        provider=display.provider,
        model=display.model,
        weekly_rate=display.weekly_rate,
        handover_date=display.handover_date,
        days=total_days,
        rent=total_rent,
        base_days=total_base,
        maintenance_days=total_maint,
        waived_days=total_waived,
        rent_from=rent_from_overall,
        charged_through=rent_through_overall,
        legs=built_legs,
        catchup_days=total_catchup,
        orphan_gap_days=total_orphans,
    )


def allowed_paid_through(*, cur_through, period_start, rent_paise, weekly_rate):
    """Furthest ISO date a manual payment may advance the rent meter.

    Guardrail from the 01-Jul-2026 incident, where Rs.1,250 (one week) advanced
    a meter five weeks and made the unpaid days unbillable forever.

    Only money that did NOT go to arrears buys new meter days — arrears repay
    days already accounted (missed). ``days = floor(rent_paise / (weekly/7))``.
    Coverage starts the day after the current meter, or at ``period_start``
    when there is no meter yet. Returns the current meter unchanged (or None)
    when the money buys no new days.
    """
    day_rate = float(weekly_rate) / 7.0
    if day_rate <= 0 or rent_paise <= 0:
        return cur_through or None
    days = int(float(rent_paise) / day_rate + 1e-6)
    if days <= 0:
        return cur_through or None
    if cur_through:
        start = date.fromisoformat(str(cur_through)[:10]) + timedelta(days=1)
    elif period_start:
        start = date.fromisoformat(str(period_start)[:10])
    else:
        return None
    return (start + timedelta(days=days - 1)).isoformat()


def advance_rent_charged_through(conn, person_id, through_date, *, assignment_ids=None):
    """Move the rent meter forward for the assignments that could have been
    billed up to ``through_date`` (normally the cycle end).

    Per assignment the new meter is ``min(through_date, returned_date - 1)``
    (the return day is free), and it only ever moves FORWARD. Assignments
    handed over after ``through_date`` are left alone — they had no days in
    this window. ``assignment_ids`` restricts the update to the legs that
    actually participated (the engine passes ``RentInfo.legs``); without it,
    every assignment of the person that overlaps is considered.

    History (2026-09 review): the previous version ran two unguarded UPDATEs
    keyed on ``person_id`` and produced three distinct money bugs — a new EV
    handed over *after* the cycle got its meter set to cycle_end (next cycle
    billed 7 days for 1 held day and skipped the handover-day-free rule);
    processing an older cycle after a newer one rolled the meter *backwards*
    and re-billed a week; and a returned EV's meter was set to
    ``returned_date - 1`` even when that was past the cycle being billed, so
    the trailing days were never billed at all.
    """
    td = date.fromisoformat(str(through_date)[:10])
    rows = conn.execute(
        "SELECT assignment_id, handover_date, returned_date, rent_charged_through "
        "FROM ev_assignments WHERE person_id=?",
        (person_id,),
    ).fetchall()
    for r in rows:
        if assignment_ids is not None and r["assignment_id"] not in assignment_ids:
            continue
        hod = _parse_date(r["handover_date"])
        ret = _parse_date(r["returned_date"])
        cur = _parse_date(r["rent_charged_through"])
        if hod is not None and hod > td:
            continue  # not held yet in this window
        new = td
        if ret is not None:
            new = min(new, ret - timedelta(days=1))
        if cur is not None and cur >= new:
            continue  # never roll a meter backwards
        conn.execute(
            "UPDATE ev_assignments SET rent_charged_through=? WHERE assignment_id=?",
            (new.isoformat(), r["assignment_id"]),
        )
