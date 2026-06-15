"""Demo seed: realistic fleet data for the live portfolio demo.

Inserts ~15 persons, riders across 3 companies, 10 EVs, 4 weeks of
transactions, COD holds, and arrears so every page looks populated.

Safe to run repeatedly -- all inserts use INSERT OR IGNORE on natural keys,
or skip when the table already has rows.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

# ── cycle helpers ────────────────────────────────────────────────────────────

def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())

TODAY       = date.today()
CYC4_END    = _monday(TODAY) - timedelta(days=1)          # last complete week end (Sun)
CYC4_START  = CYC4_END - timedelta(days=6)
CYC3_START  = CYC4_START - timedelta(days=7)
CYC3_END    = CYC4_START - timedelta(days=1)
CYC2_START  = CYC3_START - timedelta(days=7)
CYC2_END    = CYC3_START - timedelta(days=1)
CYC1_START  = CYC2_START - timedelta(days=7)
CYC1_END    = CYC2_START - timedelta(days=1)

def ds(d: date) -> str:
    return d.isoformat()

CYCLES = [
    (ds(CYC1_START), ds(CYC1_END)),
    (ds(CYC2_START), ds(CYC2_END)),
    (ds(CYC3_START), ds(CYC3_END)),
    (ds(CYC4_START), ds(CYC4_END)),
]

# ── persons ──────────────────────────────────────────────────────────────────

PERSONS = [
    (1,  "Rahul Kumar",      "4521 3304 8812"),
    (2,  "Amit Sharma",      "7734 5512 9901"),
    (3,  "Priya Singh",      "8823 4401 2234"),
    (4,  "Deepak Yadav",     "6612 9903 3341"),
    (5,  "Suresh Patel",     "5501 2287 4456"),
    (6,  "Neha Gupta",       "9934 1123 5567"),
    (7,  "Ravi Tiwari",      None),
    (8,  "Kavya Reddy",      "3301 8876 6678"),
    (9,  "Manish Verma",     "7712 3345 7789"),
    (10, "Anjali Mishra",    "4490 6623 8890"),
    (11, "Sanjay Nair",      None),
    (12, "Pooja Iyer",       "8867 1190 9901"),
    (13, "Vikram Thakur",    "2234 4478 0012"),
    (14, "Sunita Rao",       "5578 9912 1123"),
    (15, "Arun Joshi",       "6645 3301 2234"),
]

# ── rider_master rows: (rider_id, company, person_id, name, hub) ─────────────

RIDERS = [
    # Dealshare
    ("DS1001", "Dealshare", 1,  "Rahul Kumar",   "Kolkata North"),
    ("DS1002", "Dealshare", 2,  "Amit Sharma",   "Kolkata South"),
    ("DS1003", "Dealshare", 3,  "Priya Singh",   "Howrah"),
    ("DS1004", "Dealshare", 4,  "Deepak Yadav",  "Salt Lake"),
    ("DS1005", "Dealshare", 5,  "Suresh Patel",  "Kolkata North"),
    ("DS1006", "Dealshare", 11, "Sanjay Nair",   "Howrah"),
    # Blitz
    ("BL2001", "Blitz",     6,  "Neha Gupta",    "Park Street"),
    ("BL2002", "Blitz",     7,  "Ravi Tiwari",   "Ballygunge"),
    ("BL2003", "Blitz",     8,  "Kavya Reddy",   "Salt Lake"),
    ("BL2004", "Blitz",     9,  "Manish Verma",  "Dum Dum"),
    # Myntra
    ("MYN301", "Myntra",    10, "Anjali Mishra", "New Town"),
    ("MYN302", "Myntra",    12, "Pooja Iyer",    "Rajarhat"),
    ("MYN303", "Myntra",    13, "Vikram Thakur", "Sector V"),
    ("MYN304", "Myntra",    14, "Sunita Rao",    "New Town"),
    ("MYN305", "Myntra",    15, "Arun Joshi",    "Rajarhat"),
    # Rider 1 also rides Blitz (multi-company)
    ("BL2010", "Blitz",     1,  "Rahul Kumar",   "Kolkata North"),
]

# ── EV assignments: (ev_id, model_key, person_id, handover_date) ─────────────
# model_key: 0=Raft/Regular, 1=Raft/Blue, 2=Blive/Standard

EV_UNITS = [
    ("EV-KOL-001", 1),   # Raft Blue
    ("EV-KOL-002", 1),
    ("EV-KOL-003", 0),   # Raft Regular
    ("EV-KOL-004", 0),
    ("EV-KOL-005", 2),   # Blive Standard
    ("EV-KOL-006", 2),
    ("EV-KOL-007", 0),
    ("EV-KOL-008", 1),
    ("EV-KOL-009", 2),
    ("EV-KOL-010", 0),
]

# person_id → ev_id
EV_ASSIGNMENTS = {
    1:  "EV-KOL-001",
    2:  "EV-KOL-002",
    3:  "EV-KOL-003",
    4:  "EV-KOL-004",
    6:  "EV-KOL-005",
    7:  "EV-KOL-006",
    9:  "EV-KOL-007",
    11: "EV-KOL-008",
    13: "EV-KOL-009",
    15: "EV-KOL-010",
}

# EV weekly rates (mirrors seed.py EV_MODELS order after insert)
EV_WEEKLY_RATES = [1250.0, 1295.0, 1260.0]  # Regular, Blue, Standard

# ── per-person payout per cycle (company, amount) ───────────────────────────

PAYOUTS: dict[int, list[tuple[str, str, float]]] = {
    1:  [("Dealshare", "DS1001", 4200), ("Dealshare", "DS1001", 3900),
         ("Dealshare", "DS1001", 4500), ("Dealshare", "DS1001", 4100)],
    2:  [("Dealshare", "DS1002", 3800), ("Dealshare", "DS1002", 4100),
         ("Dealshare", "DS1002", 3700), ("Dealshare", "DS1002", 4300)],
    3:  [("Dealshare", "DS1003", 3200), ("Dealshare", "DS1003", 2900),
         ("Dealshare", "DS1003", 1800), ("Dealshare", "DS1003", 3400)],
    4:  [("Dealshare", "DS1004", 4600), ("Dealshare", "DS1004", 4800),
         ("Dealshare", "DS1004", 5100), ("Dealshare", "DS1004", 4900)],
    5:  [("Dealshare", "DS1005", 3100), ("Dealshare", "DS1005", 3400),
         ("Dealshare", "DS1005", 3000), ("Dealshare", "DS1005", 3600)],
    6:  [("Blitz",     "BL2001", 5200), ("Blitz",     "BL2001", 4900),
         ("Blitz",     "BL2001", 5500), ("Blitz",     "BL2001", 5100)],
    7:  [("Blitz",     "BL2002", 2800), ("Blitz",     "BL2002", 1200),
         ("Blitz",     "BL2002", 3100), ("Blitz",     "BL2002", 2900)],
    8:  [("Blitz",     "BL2003", 4100), ("Blitz",     "BL2003", 4400),
         ("Blitz",     "BL2003", 3900), ("Blitz",     "BL2003", 4200)],
    9:  [("Blitz",     "BL2004", 3700), ("Blitz",     "BL2004", 3500),
         ("Blitz",     "BL2004", 3900), ("Blitz",     "BL2004", 3600)],
    10: [("Myntra",    "MYN301", 6100), ("Myntra",    "MYN301", 5800),
         ("Myntra",    "MYN301", 6400), ("Myntra",    "MYN301", 6200)],
    11: [("Dealshare", "DS1006", 2900), ("Dealshare", "DS1006", 3200),
         ("Dealshare", "DS1006", 2700), ("Dealshare", "DS1006", 3100)],
    12: [("Myntra",    "MYN302", 5400), ("Myntra",    "MYN302", 5700),
         ("Myntra",    "MYN302", 5200), ("Myntra",    "MYN302", 5600)],
    13: [("Myntra",    "MYN303", 4800), ("Myntra",    "MYN303", 4500),
         ("Myntra",    "MYN303", 5000), ("Myntra",    "MYN303", 4700)],
    14: [("Myntra",    "MYN304", 5900), ("Myntra",    "MYN304", 6100),
         ("Myntra",    "MYN304", 5700), ("Myntra",    "MYN304", 6300)],
    15: [("Myntra",    "MYN305", 3300), ("Myntra",    "MYN305", 3600),
         ("Myntra",    "MYN305", 3100), ("Myntra",    "MYN305", 3500)],
}


def _already_seeded(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT COUNT(*) FROM person_registry").fetchone()
    return (row[0] or 0) > 0


def seed_demo(conn: sqlite3.Connection) -> None:
    """Insert demo fleet data. No-op if persons already exist."""
    if _already_seeded(conn):
        return

    # ── persons ──────────────────────────────────────────────────────────────
    for pid, name, kyc in PERSONS:
        conn.execute(
            "INSERT OR IGNORE INTO person_registry "
            "(person_id, display_name, kyc_no) VALUES (?,?,?)",
            (pid, name, kyc),
        )

    # ── riders ───────────────────────────────────────────────────────────────
    for rider_id, company, person_id, name, hub in RIDERS:
        conn.execute(
            "INSERT OR IGNORE INTO rider_master "
            "(rider_id, company, person_id, name, hub) VALUES (?,?,?,?,?)",
            (rider_id, company, person_id, name, hub),
        )

    # ── set deduction_company on person (for EV rent tracking) ───────────────
    for rider_id, company, person_id, _, _ in RIDERS:
        conn.execute(
            "UPDATE person_registry SET deduction_company=?, deduction_rider_id=? "
            "WHERE person_id=? AND deduction_company IS NULL",
            (company, rider_id, person_id),
        )

    # ── fetch model_ids in insertion order ───────────────────────────────────
    model_rows = conn.execute(
        "SELECT model_id FROM ev_models ORDER BY model_id"
    ).fetchall()
    model_ids = [r[0] for r in model_rows]  # [Regular, Blue, Standard]

    # ── EV units ─────────────────────────────────────────────────────────────
    for ev_id, model_idx in EV_UNITS:
        conn.execute(
            "INSERT OR IGNORE INTO ev_units (ev_id, model_id, status) VALUES (?,?,?)",
            (ev_id, model_ids[model_idx], "in_use"),
        )

    # ── EV assignments (current, open) ───────────────────────────────────────
    handover = ds(CYC1_START - timedelta(days=14))
    for person_id, ev_id in EV_ASSIGNMENTS.items():
        conn.execute(
            "INSERT OR IGNORE INTO ev_assignments "
            "(person_id, ev_id, handover_date) VALUES (?,?,?)",
            (person_id, ev_id, handover),
        )
        # weekly rate for this EV
        mid = conn.execute(
            "SELECT model_id FROM ev_units WHERE ev_id=?", (ev_id,)
        ).fetchone()[0]
        weekly = conn.execute(
            "SELECT weekly_rate FROM ev_models WHERE model_id=?", (mid,)
        ).fetchone()[0]
        # update person deduction link
        conn.execute(
            "UPDATE person_registry SET deduction_company=deduction_company "
            "WHERE person_id=?", (person_id,)
        )
        _ = weekly  # used below in transactions

    # ── transactions + balances ───────────────────────────────────────────────
    # For each person build 4 cycles of: PAYOUT → RENT (if EV) → net balance
    for person_id, payout_rows in PAYOUTS.items():
        running_balance = 0.0

        # carry-forward dues for person 3 (cycle 3 payout was low)
        ev_id = EV_ASSIGNMENTS.get(person_id)
        ev_weekly = 0.0
        if ev_id:
            mid = conn.execute(
                "SELECT model_id FROM ev_units WHERE ev_id=?", (ev_id,)
            ).fetchone()[0]
            ev_weekly = conn.execute(
                "SELECT weekly_rate FROM ev_models WHERE model_id=?", (mid,)
            ).fetchone()[0]

        for i, (cyc_start, cyc_end) in enumerate(CYCLES):
            company, rider_id, gross = payout_rows[i]

            # PAYOUT transaction
            running_balance += gross
            conn.execute(
                "INSERT INTO transactions "
                "(person_id, rider_id, company, cycle_start, cycle_end, "
                " event_type, amount, balance_after, remarks, created_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (person_id, rider_id, company, cyc_start, cyc_end,
                 "PAYOUT", gross, running_balance,
                 f"Payout cycle {cyc_start}", "system"),
            )

            # RENT transaction (if person has an EV)
            if ev_weekly:
                rent = -ev_weekly
                if running_balance + rent < 0:
                    # Can't cover — mark as missed
                    rent_actual = -running_balance if running_balance > 0 else 0
                    missed = ev_weekly - abs(rent_actual)
                    if rent_actual:
                        running_balance -= rent_actual
                        conn.execute(
                            "INSERT INTO transactions "
                            "(person_id, rider_id, company, cycle_start, cycle_end, "
                            " event_type, amount, balance_after, days, remarks, created_by) "
                            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                            (person_id, rider_id, company, cyc_start, cyc_end,
                             "RENT", -rent_actual, running_balance, 7,
                             "Partial EV rent", "system"),
                        )
                    conn.execute(
                        "INSERT INTO transactions "
                        "(person_id, rider_id, company, cycle_start, cycle_end, "
                        " event_type, amount, balance_after, days, remarks, created_by) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (person_id, rider_id, company, cyc_start, cyc_end,
                         "RENT_MISSED", -missed, running_balance, 7,
                         "EV rent shortfall carried to arrears", "system"),
                    )
                    # update arrears
                    conn.execute(
                        "INSERT INTO ev_arrears (person_id, total_missed, outstanding) "
                        "VALUES (?,?,?) ON CONFLICT(person_id) DO UPDATE SET "
                        "total_missed=total_missed+excluded.total_missed, "
                        "outstanding=outstanding+excluded.outstanding",
                        (person_id, missed, missed),
                    )
                else:
                    running_balance += rent
                    conn.execute(
                        "INSERT INTO transactions "
                        "(person_id, rider_id, company, cycle_start, cycle_end, "
                        " event_type, amount, balance_after, days, remarks, created_by) "
                        "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (person_id, rider_id, company, cyc_start, cyc_end,
                         "RENT", rent, running_balance, 7,
                         "Weekly EV rent", "system"),
                    )

        # final balance
        conn.execute(
            "INSERT OR REPLACE INTO balances (person_id, current_balance, last_updated) "
            "VALUES (?,?, datetime('now'))",
            (person_id, round(running_balance, 2)),
        )
        # status tracking
        conn.execute(
            "INSERT OR IGNORE INTO status_tracking (person_id, status, last_seen) "
            "VALUES (?, 'active', date('now'))",
            (person_id,),
        )

    # ── COD holds (Myntra) ────────────────────────────────────────────────────
    cod_data = [
        (ds(CYC3_START), ds(CYC3_END), "Myntra", "MYN301", 10, "ORD-88823", 450.0),
        (ds(CYC3_START), ds(CYC3_END), "Myntra", "MYN303", 13, "ORD-88901", 320.0),
        (ds(CYC4_START), ds(CYC4_END), "Myntra", "MYN302", 12, "ORD-90112", 780.0),
        (ds(CYC4_START), ds(CYC4_END), "Myntra", "MYN305", 15, "ORD-90245", 210.0),
        (ds(CYC4_START), ds(CYC4_END), "Myntra", "MYN301", 10, "ORD-90389", 560.0),
    ]
    for cs, ce, company, rider_id, person_id, order_no, amount in cod_data:
        conn.execute(
            "INSERT OR IGNORE INTO cod_holds "
            "(cycle_start, cycle_end, company, rider_id, person_id, "
            " order_number, amount, source) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (cs, ce, company, rider_id, person_id, order_no, amount, "myntra_column"),
        )

    # ── one EV in maintenance ─────────────────────────────────────────────────
    conn.execute(
        "INSERT OR IGNORE INTO ev_maintenance "
        "(ev_id, from_date, reason, created_by) VALUES (?,?,?,?)",
        ("EV-KOL-006", ds(CYC4_START), "Battery replacement", "admin@demo.com"),
    )

    conn.commit()
    print("[demo_seed] Inserted demo fleet data: 15 persons, 16 riders, 10 EVs, 4 cycles.")
