"""Regression: a missed-rent cycle must advance the EV meter so a later
overlapping cycle does not re-bill the same days while arrears are also
recovered (which double-charged the rider). See engine.py absence pass."""

import io
from datetime import date

from openpyxl import Workbook

from payout.domain.engine import process_cycle


def _blitz_file(rows):
    wb = Workbook()
    ws = wb.active
    ws.append(["rider_id", "net_pay"])
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_missed_rent_then_catchup_does_not_double_charge(db):
    pid = db.execute(
        "INSERT INTO person_registry (display_name, deduction_company, deduction_rider_id) "
        "VALUES ('P','Blitz','P1')"
    ).lastrowid
    db.execute(
        "INSERT INTO rider_master (rider_id,company,person_id,name,is_active) "
        "VALUES ('P1','Blitz',?,'P',1)",
        (pid,),
    )
    db.execute("INSERT OR IGNORE INTO balances (person_id,current_balance) VALUES (?,0)", (pid,))
    db.execute(
        "INSERT OR IGNORE INTO ev_arrears (person_id,total_missed,total_recovered,outstanding) "
        "VALUES (?,0,0,0)",
        (pid,),
    )
    mid = db.execute(
        "SELECT model_id FROM ev_models WHERE provider='Raft' AND model_name='Regular'"
    ).fetchone()["model_id"]
    db.execute("INSERT INTO ev_units (ev_id,model_id,status) VALUES ('EVX',?, 'in_use')", (mid,))
    db.execute(
        "INSERT INTO ev_assignments (person_id,ev_id,rent_charged_through) "
        "VALUES (?, 'EVX', '2026-06-13')",
        (pid,),
    )
    db.commit()

    # Cycle A: rider ABSENT from Blitz 06-14..06-20 -> rent falls to arrears.
    process_cycle(
        "Blitz", date(2026, 6, 14), date(2026, 6, 20), _blitz_file([("OTHER", 0)]), commit=True
    )
    # Cycle B: rider PRESENT 06-21..06-27 with a payout big enough to settle.
    process_cycle(
        "Blitz", date(2026, 6, 21), date(2026, 6, 27), _blitz_file([("P1", 6000)]), commit=True
    )

    agg = {
        r["event_type"]: r
        for r in db.execute(
            "SELECT event_type, SUM(-amount) AS debit, SUM(amount) AS credit "
            "FROM transactions WHERE person_id=? GROUP BY event_type",
            (pid,),
        )
    }
    rent_billed = agg["RENT"]["debit"]
    recovered = agg["RENT_RECOVERED"]["credit"]
    released = agg["RELEASE"]["debit"]
    arrears = db.execute("SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)).fetchone()[
        "outstanding"
    ]

    # 14 EV-days (06-14..06-27) at Rs.1250/wk = 250000 paise, billed exactly once.
    assert rent_billed == 125000  # catch-up bills only the fresh 7 days
    assert recovered == 125000  # the missed 7 days, clawed from arrears
    assert rent_billed + recovered == 250000  # charged once -- no double-charge
    assert released == 350000
    assert arrears == 0


def test_stuck_meter_catchup_is_capped_to_cycle(db):
    """STRONG guardrail: with a meter left a week behind cycle_start (a
    pre-fix stuck meter) while that week already sits in arrears — its
    RENT_MISSED event is on the ledger — a present cycle bills only its own
    days, never a catch-up that would double-charge the arrears days."""
    pid = db.execute(
        "INSERT INTO person_registry (display_name, deduction_company, deduction_rider_id) "
        "VALUES ('S','Blitz','S1')"
    ).lastrowid
    db.execute(
        "INSERT INTO rider_master (rider_id,company,person_id,name,is_active) "
        "VALUES ('S1','Blitz',?,'S',1)",
        (pid,),
    )
    db.execute("INSERT OR IGNORE INTO balances (person_id,current_balance) VALUES (?,0)", (pid,))
    # The prior missed week is already sitting in arrears.
    db.execute(
        "INSERT OR IGNORE INTO ev_arrears (person_id,total_missed,total_recovered,outstanding) "
        "VALUES (?,125000,0,125000)",
        (pid,),
    )
    mid = db.execute(
        "SELECT model_id FROM ev_models WHERE provider='Raft' AND model_name='Regular'"
    ).fetchone()["model_id"]
    db.execute("INSERT INTO ev_units (ev_id,model_id,status) VALUES ('EVS1',?, 'in_use')", (mid,))
    # Meter stuck at 06-14 — a full week behind the 06-22 cycle start — and
    # the missed week is on the books as RENT_MISSED (pre-fix data shape).
    db.execute(
        "INSERT INTO ev_assignments (person_id,ev_id,rent_charged_through) "
        "VALUES (?, 'EVS1', '2026-06-14')",
        (pid,),
    )
    db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, days) "
        "VALUES (?, 'S1', 'Blitz', '2026-06-15', '2026-06-21', 'RENT_MISSED', -125000, 0, 7)",
        (pid,),
    )
    db.commit()

    process_cycle(
        "Blitz", date(2026, 6, 22), date(2026, 6, 28), _blitz_file([("S1", 6000)]), commit=True
    )

    rent = db.execute(
        "SELECT event_type, SUM(-amount) AS debit, MAX(days) AS days "
        "FROM transactions WHERE person_id=? AND event_type='RENT' "
        "GROUP BY event_type",
        (pid,),
    ).fetchone()
    # 7-day cycle billed as 7 days / Rs.1250 — NOT a 14-day (Rs.2500) catch-up.
    assert rent["days"] == 7, f"expected 7 days billed, got {rent['days']}"
    assert rent["debit"] == 125000, f"expected 125000 paise, got {rent['debit']}"


def test_absence_missed_is_capped_when_arrears(db):
    """The absence pass must not inflate RENT_MISSED via a stuck-meter catch-up:
    a rider with prior arrears who is absent again gets missed for THIS cycle
    only, not a catch-up that double-counts the earlier missed week."""
    pid = db.execute(
        "INSERT INTO person_registry (display_name, deduction_company, deduction_rider_id) "
        "VALUES ('T','Blitz','T1')"
    ).lastrowid
    db.execute(
        "INSERT INTO rider_master (rider_id,company,person_id,name,is_active) "
        "VALUES ('T1','Blitz',?,'T',1)",
        (pid,),
    )
    db.execute("INSERT OR IGNORE INTO balances (person_id,current_balance) VALUES (?,0)", (pid,))
    db.execute(
        "INSERT OR IGNORE INTO ev_arrears (person_id,total_missed,total_recovered,outstanding) "
        "VALUES (?,125000,0,125000)",
        (pid,),
    )  # prior week already missed
    mid = db.execute(
        "SELECT model_id FROM ev_models WHERE provider='Raft' AND model_name='Regular'"
    ).fetchone()["model_id"]
    db.execute("INSERT INTO ev_units (ev_id,model_id,status) VALUES ('EVT1',?, 'in_use')", (mid,))
    db.execute(
        "INSERT INTO ev_assignments (person_id,ev_id,rent_charged_through) "
        "VALUES (?, 'EVT1', '2026-06-14')",
        (pid,),
    )  # meter stuck a week back; that week is already RENT_MISSED
    db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, days) "
        "VALUES (?, 'T1', 'Blitz', '2026-06-15', '2026-06-21', 'RENT_MISSED', -125000, 0, 7)",
        (pid,),
    )
    db.commit()

    # T1 is ABSENT from this 7-day cycle (file has a different rider).
    process_cycle(
        "Blitz", date(2026, 6, 22), date(2026, 6, 28), _blitz_file([("OTHER", 0)]), commit=True
    )

    m = db.execute(
        "SELECT MAX(days) AS days, SUM(-amount) AS amt FROM transactions "
        "WHERE person_id=? AND event_type='RENT_MISSED' AND cycle_start='2026-06-22'",
        (pid,),
    ).fetchone()
    assert m["days"] == 7, f"expected 7 missed days, got {m['days']}"
    assert m["amt"] == 125000, f"expected 125000 paise missed, got {m['amt']}"
