from datetime import date

import pytest

from payout.domain.rent import chargeable_days, rent_for_days, resolve_rent

CS = date(2026, 3, 2)  # cycle start (Mon)
CE = date(2026, 3, 8)  # cycle end (Sun) -> 7-day cycle


@pytest.mark.parametrize(
    "handover,expected",
    [
        (None, 7),  # no handover date -> full week
        (date(2026, 2, 1), 7),  # held well before the cycle
        (CS, 6),  # handover on cycle start -> handover day free, bill Tue..Sun
        (date(2026, 3, 3), 5),  # Tue handover -> Wed..Sun
        (date(2026, 3, 4), 4),  # Wed handover -> Thu..Sun
        (date(2026, 3, 7), 1),  # Sat handover -> Sun
        (CE, 0),  # handover on cycle end -> nothing
        (date(2026, 3, 20), 0),  # after the cycle -> nothing
    ],
)
def test_chargeable_days(handover, expected):
    assert chargeable_days(CS, CE, handover) == expected


@pytest.mark.parametrize(
    "weekly,days,expected",
    [
        (1250, 7, 1250.0),  # Raft Regular full week
        (1295, 7, 1295.0),  # Raft Blue full week
        (1260, 7, 1260.0),  # Blive full week
        (1260, 5, 900.0),  # 1260/7*5
        (1260, 4, 720.0),  # 1260/7*4
        (1250, 0, 0.0),  # no days
        (1250, -2, 0.0),  # guard against negatives
    ],
)
def test_rent_for_days(weekly, days, expected):
    assert rent_for_days(weekly, days) == pytest.approx(expected)


def test_resolve_rent_partial_week(db):
    pid = db.execute("INSERT INTO person_registry (display_name) VALUES ('T')").lastrowid
    db.execute("INSERT OR IGNORE INTO balances (person_id, current_balance) VALUES (?,0)", (pid,))
    mid = db.execute("SELECT model_id FROM ev_models WHERE provider='Blive'").fetchone()["model_id"]
    db.execute("INSERT INTO ev_units (ev_id, model_id, status) VALUES ('B1', ?, 'in_use')", (mid,))
    db.execute(
        "INSERT INTO ev_assignments (person_id, ev_id, handover_date) VALUES (?, 'B1', '2026-03-04')",  # noqa: E501
        (pid,),
    )
    db.commit()
    info = resolve_rent(db, pid, CS, CE)
    assert info.has_ev
    assert info.weekly_rate == 126000  # paise
    assert info.days == 4
    assert info.rent == pytest.approx(72000.0)  # paise


def test_resolve_rent_no_ev(db):
    pid = db.execute("INSERT INTO person_registry (display_name) VALUES ('NoEV')").lastrowid
    db.commit()
    info = resolve_rent(db, pid, CS, CE)
    assert not info.has_ev
    assert info.rent == 0.0
