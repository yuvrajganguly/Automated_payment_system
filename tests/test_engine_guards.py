"""Engine correctness regressions from the 2026-09-01 review.

Rent meter (advance_rent_charged_through):
  * an EV handed over AFTER the cycle must not have its meter set to cycle_end
    (next cycle then billed 7 days for 1 held day);
  * processing an OLDER cycle after a newer one must not roll the meter back;
  * a returned EV's meter must stop at the cycle end, not at returned_date-1
    when that is past the cycle (trailing days were never billed).
Parser / engine input hygiene:
  * duplicate rider ids in one file are rejected (they were paid twice);
  * an unreadable payout cell keeps the rider PRESENT (was: dropped -> absent ->
    RENT_MISSED arrears) and blocks commit.
Ledger:
  * manual adjustments for a person with no balances row are not lost;
  * a cycle cannot be committed twice unless forced; forcing replaces holds.
"""
from __future__ import annotations

import io
from datetime import date

import pytest
from openpyxl import Workbook

from payout.domain.adjustments import post_adjustment
from payout.domain.engine import CycleAlreadyCommitted, UnreadablePayouts, process_cycle
from payout.domain.rent import advance_rent_charged_through, resolve_rent
from tests.conftest import assign, make_ev, make_person, make_rider

RAFT_WEEK = 125000  # Raft Regular, paise
RAFT_DAY = 17857    # 125000/7 rounded half-up


def _file(rows, headers=("rider_id", "net_pay")):
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _meter(db, aid):
    return db.execute(
        "SELECT rent_charged_through FROM ev_assignments WHERE assignment_id=?", (aid,)
    ).fetchone()[0]


def _raft_rider(db, rid="P1", company="Blitz"):
    pid = make_person(db, "P", balance=0, arrears=0)
    make_rider(db, pid, rid, company, "P")
    db.execute(
        "UPDATE person_registry SET deduction_company=?, deduction_rider_id=? WHERE person_id=?",
        (company, rid, pid),
    )
    db.commit()
    return pid


# ── rent meter ───────────────────────────────────────────────────────────────


def test_meter_ignores_ev_handed_over_after_the_cycle(db):
    pid = _raft_rider(db)
    make_ev(db, "EV-A", provider="Raft", model="Regular")
    make_ev(db, "EV-B", provider="Raft", model="Regular")
    # EV-A returned 06-10 (meter 06-07); EV-B handed over 06-20, after the cycle.
    a = assign(db, pid, "EV-A", returned="2026-06-10", charged_through="2026-06-07")
    b = assign(db, pid, "EV-B", handover="2026-06-20")
    db.commit()

    cs, ce = date(2026, 6, 8), date(2026, 6, 14)
    info = resolve_rent(db, pid, cs, ce)
    assert info.days == 2 and info.rent == 2 * RAFT_DAY  # 06-08, 06-09 on EV-A
    advance_rent_charged_through(db, pid, ce, assignment_ids={L.assignment_id for L in info.legs})
    db.commit()

    assert _meter(db, a) == "2026-06-09"   # capped at return day - 1
    assert _meter(db, b) is None            # untouched: not held yet (was set to 06-14)

    # Next cycle: EV-B held from 06-21 (handover day free) -> exactly 1 day, not 7.
    nxt = resolve_rent(db, pid, date(2026, 6, 15), date(2026, 6, 21))
    assert nxt.days == 1 and nxt.rent == RAFT_DAY


def test_meter_never_rolls_backwards(db):
    pid = _raft_rider(db)
    make_ev(db, "EV-A", provider="Raft", model="Regular")
    a = assign(db, pid, "EV-A", charged_through="2026-06-14")
    db.commit()
    # A late file for the OLDER week 06-01..06-07 arrives after 06-08..06-14 was billed.
    advance_rent_charged_through(db, pid, date(2026, 6, 7))
    db.commit()
    assert _meter(db, a) == "2026-06-14"
    # and the newer week is therefore not billable again
    again = resolve_rent(db, pid, date(2026, 6, 8), date(2026, 6, 14))
    assert again.days == 0 and again.rent == 0


def test_returned_ev_meter_stops_at_cycle_end(db):
    pid = _raft_rider(db)
    make_ev(db, "EV-A", provider="Raft", model="Regular")
    # Returned 06-10, but we are billing the week that ended 06-07.
    a = assign(db, pid, "EV-A", returned="2026-06-10", charged_through="2026-05-31")
    db.commit()
    advance_rent_charged_through(db, pid, date(2026, 6, 7))
    db.commit()
    assert _meter(db, a) == "2026-06-07"    # was 06-09: 06-08 and 06-09 lost forever
    trailing = resolve_rent(db, pid, date(2026, 6, 8), date(2026, 6, 14))
    assert trailing.days == 2 and trailing.rent == 2 * RAFT_DAY


def test_engine_advances_only_the_legs_it_billed(db):
    pid = _raft_rider(db)
    make_ev(db, "EV-A", provider="Raft", model="Regular")
    make_ev(db, "EV-B", provider="Raft", model="Regular")
    assign(db, pid, "EV-A", returned="2026-06-10", charged_through="2026-06-07")
    b = assign(db, pid, "EV-B", handover="2026-06-20")
    db.commit()
    process_cycle("Blitz", date(2026, 6, 8), date(2026, 6, 14), _file([("P1", 5000)]), commit=True)
    assert _meter(db, b) is None
    rent = db.execute(
        "SELECT -SUM(amount) FROM transactions WHERE person_id=? AND event_type='RENT'", (pid,)
    ).fetchone()[0]
    assert rent == 2 * RAFT_DAY


# ── file hygiene ─────────────────────────────────────────────────────────────


def test_duplicate_rider_rows_are_rejected(db):
    _raft_rider(db)
    with pytest.raises(ValueError, match="more than once"):
        process_cycle("Blitz", date(2026, 6, 1), date(2026, 6, 7),
                      _file([("P1", 3000), ("P1", 3000)]), commit=False)
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_unreadable_payout_keeps_rider_present_and_blocks_commit(db):
    pid = _raft_rider(db)
    make_ev(db, "EV-A", provider="Raft", model="Regular")
    assign(db, pid, "EV-A", charged_through="2026-05-31")
    db.commit()
    f = _file([("P1", "N/A"), ("OTHER", 100)])

    preview = process_cycle("Blitz", date(2026, 6, 1), date(2026, 6, 7), f, commit=False)
    assert preview.unreadable_riders == [{"rider_id": "P1", "name": "P", "cell": "N/A"}]
    assert not preview.inactive_rows, "an unreadable row is not an absence"
    assert any("unreadable payout" in w for w in preview.warnings)

    with pytest.raises(UnreadablePayouts):
        process_cycle("Blitz", date(2026, 6, 1), date(2026, 6, 7), f, commit=True)
    assert db.execute(
        "SELECT COUNT(*) FROM transactions WHERE event_type='RENT_MISSED'"
    ).fetchone()[0] == 0
    assert db.execute("SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()[0] == 0


def test_numeric_rider_ids_lose_the_excel_float_suffix(db):
    pid = make_person(db, "N", balance=0)
    make_rider(db, pid, "8906377190", "Blitz", "N")
    db.commit()
    wb = Workbook(); ws = wb.active
    ws.append(["rider_id", "net_pay"]); ws.append([8906377190, 500])   # numeric cell
    buf = io.BytesIO(); wb.save(buf)
    r = process_cycle("Blitz", date(2026, 6, 1), date(2026, 6, 7), buf.getvalue(), commit=False)
    assert r.unknown_ids == [] and len(r.pay_rows) == 1


# ── ledger ───────────────────────────────────────────────────────────────────


def test_adjustment_creates_the_balance_row(db):
    pid = make_person(db, "New rider")            # no balances row, like onboarding
    db.commit()
    new_bal = post_adjustment(db, pid, -50000, "Advance given", "tester")
    db.commit()
    assert new_bal == -50000
    assert db.execute(
        "SELECT current_balance FROM balances WHERE person_id=?", (pid,)
    ).fetchone()[0] == -50000
    txn = db.execute(
        "SELECT amount, balance_after FROM transactions WHERE person_id=? AND event_type='ADJUSTMENT'",
        (pid,),
    ).fetchone()
    assert (txn[0], txn[1]) == (-50000, -50000)


def test_second_commit_of_same_cycle_is_refused_unless_forced(db):
    _raft_rider(db)
    f = _file([("P1", 3000)])
    process_cycle("Blitz", date(2026, 6, 1), date(2026, 6, 7), f, commit=True)
    with pytest.raises(CycleAlreadyCommitted):
        process_cycle("Blitz", date(2026, 6, 1), date(2026, 6, 7), f, commit=True)
    assert db.execute(
        "SELECT COUNT(*) FROM transactions WHERE event_type='PAYOUT'"
    ).fetchone()[0] == 1
    # A dry run of an already-committed cycle is still allowed.
    process_cycle("Blitz", date(2026, 6, 1), date(2026, 6, 7), f, commit=False)
    # force re-runs (documented: appends ledger rows again)
    process_cycle("Blitz", date(2026, 6, 1), date(2026, 6, 7), f, commit=True, force=True)
    assert db.execute("SELECT COUNT(*) FROM company_cycles").fetchone()[0] == 1


def test_forced_rerun_replaces_cod_holds_instead_of_doubling(db):
    pid = make_person(db, "M", balance=0)
    make_rider(db, pid, "M1", "Myntra", "M")
    db.commit()
    f = _file([("M1", 2000, 750)], headers=("Worker Code", "Final Payout", "COD-Pending"))
    process_cycle("Myntra", date(2026, 6, 1), date(2026, 6, 7), f, commit=True)
    process_cycle("Myntra", date(2026, 6, 1), date(2026, 6, 7), f, commit=True, force=True)
    total = db.execute(
        "SELECT SUM(amount) FROM cod_holds WHERE rider_id='M1' AND company='Myntra'"
    ).fetchone()[0]
    assert total == 75000, "HOLD sheet total doubled on re-run"


# ── Nykaa: Blitz rider ids are reused ────────────────────────────────────────


def test_nykaa_file_links_blitz_rider_ids_automatically(db):
    pid = _raft_rider(db, rid="B77", company="Blitz")
    db.commit()
    r = process_cycle("Nykaa", date(2026, 6, 1), date(2026, 6, 7), _file([("B77", 1500)]),
                      commit=True)
    assert r.unknown_ids == []
    assert r.auto_linked == [
        {"rider_id": "B77", "person_id": pid, "name": "P", "linked_from": "Blitz"}
    ]
    assert len(r.pay_rows) == 1 and r.pay_rows[0].person_id == pid
    row = db.execute(
        "SELECT person_id FROM rider_master WHERE rider_id='B77' AND company='Nykaa'"
    ).fetchone()
    assert row and row[0] == pid


def test_nykaa_id_unknown_at_blitz_is_still_unknown(db):
    r = process_cycle("Nykaa", date(2026, 6, 1), date(2026, 6, 7), _file([("ZZ9", 1500)]),
                      commit=False)
    assert r.unknown_ids == ["ZZ9"] and r.auto_linked == []
