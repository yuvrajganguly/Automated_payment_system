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
    process_cycle("Blitz", date(2026, 6, 14), date(2026, 6, 20), _blitz_file([("OTHER", 0)]), commit=True)
    # Cycle B: rider PRESENT 06-21..06-27 with a payout big enough to settle.
    process_cycle("Blitz", date(2026, 6, 21), date(2026, 6, 27), _blitz_file([("P1", 6000)]), commit=True)

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
    arrears = db.execute(
        "SELECT outstanding FROM ev_arrears WHERE person_id=?", (pid,)
    ).fetchone()["outstanding"]

    # 14 EV-days (06-14..06-27) at Rs.1250/wk = 250000 paise, billed exactly once.
    assert rent_billed == 125000          # catch-up bills only the fresh 7 days
    assert recovered == 125000            # the missed 7 days, clawed from arrears
    assert rent_billed + recovered == 250000   # charged once -- no double-charge
    assert released == 350000
    assert arrears == 0


def test_stuck_meter_catchup_with_recovery_warns(db):
    """A stuck meter (pre-fix state) + arrears recovered in one catch-up cycle
    must raise a double-charge warning for the operator."""
    pid = db.execute(
        "INSERT INTO person_registry (display_name, deduction_company, deduction_rider_id) "
        "VALUES ('Q','Blitz','Q1')"
    ).lastrowid
    db.execute(
        "INSERT INTO rider_master (rider_id,company,person_id,name,is_active) "
        "VALUES ('Q1','Blitz',?,'Q',1)", (pid,))
    db.execute("INSERT OR IGNORE INTO balances (person_id,current_balance) VALUES (?,0)", (pid,))
    # A prior missed week already sitting in arrears (on the books)...
    db.execute(
        "INSERT OR IGNORE INTO ev_arrears (person_id,total_missed,total_recovered,outstanding) "
        "VALUES (?,125000,0,125000)", (pid,))
    mid = db.execute(
        "SELECT model_id FROM ev_models WHERE provider='Raft' AND model_name='Regular'"
    ).fetchone()["model_id"]
    db.execute("INSERT INTO ev_units (ev_id,model_id,status) VALUES ('EVQ',?, 'in_use')", (mid,))
    # ...but the meter was left stuck a week behind the cycle start (pre-fix).
    db.execute(
        "INSERT INTO ev_assignments (person_id,ev_id,rent_charged_through) "
        "VALUES (?, 'EVQ', '2026-06-13')", (pid,))
    db.commit()

    # One 7-day cycle, rider present with a big payout -> engine bills a 14-day
    # catch-up AND recovers the arrears -> double-charge risk -> must warn.
    result = process_cycle(
        "Blitz", date(2026, 6, 21), date(2026, 6, 27),
        _blitz_file([("Q1", 6000)]), commit=True)
    assert any("double-charge" in w for w in result.warnings), \
        f"expected a double-charge warning; got {result.warnings}"
