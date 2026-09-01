from datetime import date

import pytest

from payout.domain.arrears import apply_settlement, get_arrears, record_missed_rent, record_recovery


@pytest.mark.parametrize(
    "payout,rent,prev,arr,exp",
    [
        # plenty: clears rent + arrears + dues, releases the rest
        (
            3000,
            1260,
            -300,
            500,
            dict(
                arrears_recovered=500, dues_cleared=300, released=940, new_balance=0, new_arrears=0
            ),
        ),
        # covers rent + arrears, partial dues, nothing released
        (
            2000,
            1260,
            -300,
            500,
            dict(
                arrears_recovered=500, dues_cleared=240, released=0, new_balance=-60, new_arrears=0
            ),
        ),
        # payout < rent: shortfall to dues, arrears untouched
        (
            800,
            1260,
            0,
            500,
            dict(
                rent_short=460, arrears_recovered=0, released=0, new_balance=-460, new_arrears=500
            ),
        ),
        # arrears take priority over general dues
        (
            600,
            0,
            -300,
            400,
            dict(
                arrears_recovered=400, dues_cleared=200, released=0, new_balance=-100, new_arrears=0
            ),
        ),
    ],
)
def test_apply_settlement(payout, rent, prev, arr, exp):
    s = apply_settlement(payout, rent, prev, arr)
    for key, val in exp.items():
        assert getattr(s, key) == pytest.approx(val), (key, getattr(s, key), val)


def test_missed_then_recovered(db):
    pid = db.execute("INSERT INTO person_registry (display_name) VALUES ('A')").lastrowid
    db.execute("INSERT OR IGNORE INTO balances (person_id,current_balance) VALUES (?,0)", (pid,))
    db.execute(
        "INSERT OR IGNORE INTO ev_arrears (person_id,total_missed,total_recovered,outstanding) VALUES (?,0,0,0)",  # noqa: E501
        (pid,),
    )
    db.commit()
    record_missed_rent(
        db, pid, 360, date(2026, 3, 2), date(2026, 3, 8), rider_id="J1", company="Jiffy", days=2
    )
    db.commit()
    assert get_arrears(db, pid) == (360.0, 0.0, 360.0)
    assert (
        record_recovery(db, pid, 200, date(2026, 3, 9), date(2026, 3, 15), company="Jiffy") == 200.0
    )
    db.commit()
    assert get_arrears(db, pid) == (360.0, 200.0, 160.0)
    assert (
        db.execute("SELECT COUNT(*) FROM transactions WHERE event_type='RENT_MISSED'").fetchone()[0]
        == 1
    )
    assert (
        db.execute(
            "SELECT COUNT(*) FROM transactions WHERE event_type='RENT_RECOVERED'"
        ).fetchone()[0]
        == 1
    )
