from datetime import date

import pytest

from payout.domain.adjustments import log_maintenance, post_adjustment
from payout.domain.rent import resolve_rent

CS, CE = date(2026, 3, 2), date(2026, 3, 8)  # 7-day cycle


def _blive_rider(db, handover=None):
    pid = db.execute("INSERT INTO person_registry (display_name) VALUES ('M')").lastrowid
    db.execute("INSERT OR IGNORE INTO balances (person_id,current_balance) VALUES (?,0)", (pid,))
    mid = db.execute("SELECT model_id FROM ev_models WHERE provider='Blive'").fetchone()["model_id"]
    db.execute("INSERT INTO ev_units (ev_id,model_id,status) VALUES ('B1',?,'in_use')", (mid,))
    db.execute("INSERT INTO ev_assignments (person_id,ev_id,handover_date) VALUES (?, 'B1', ?)", (pid, handover))
    db.commit()
    return pid


def test_maintenance_reduces_rent(db):
    pid = _blive_rider(db)
    assert resolve_rent(db, pid, CS, CE).rent == 1260.0
    log_maintenance(db, "B1", date(2026, 3, 4), date(2026, 3, 5), "workshop", "t")
    db.commit()
    info = resolve_rent(db, pid, CS, CE)
    assert info.maintenance_days == 2 and info.days == 5
    assert info.rent == pytest.approx(900.0)


def test_ad_hoc_waive_days(db):
    pid = _blive_rider(db)
    info = resolve_rent(db, pid, CS, CE, waive_days=2)
    assert info.days == 5 and info.rent == pytest.approx(900.0)


def test_full_waiver(db):
    pid = _blive_rider(db)
    assert resolve_rent(db, pid, CS, CE, waive_all=True).rent == 0.0


def test_rate_override(db):
    pid = _blive_rider(db)
    assert resolve_rent(db, pid, CS, CE, rent_override=1000).rent == 1000.0


def test_post_adjustment(db):
    pid = db.execute("INSERT INTO person_registry (display_name) VALUES ('A')").lastrowid
    db.execute("INSERT OR IGNORE INTO balances (person_id,current_balance) VALUES (?,0)", (pid,))
    db.commit()
    assert post_adjustment(db, pid, -300, "penalty", "t") == -300.0
    assert post_adjustment(db, pid, 100, "goodwill", "t") == -200.0
    assert db.execute("SELECT COUNT(*) FROM transactions WHERE event_type='ADJUSTMENT'").fetchone()[0] == 2


def test_adjustment_requires_reason(db):
    pid = db.execute("INSERT INTO person_registry (display_name) VALUES ('A')").lastrowid
    db.execute("INSERT OR IGNORE INTO balances (person_id,current_balance) VALUES (?,0)", (pid,))
    db.commit()
    with pytest.raises(ValueError):
        post_adjustment(db, pid, 100, "", "t")
