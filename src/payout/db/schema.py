"""Database schema (DDL).

One canonical human is a ``person`` with a stable ``person_id``; a person may
hold many ``rider_id``s across and within companies but rents at most one EV at
a time. EV rent, dues, and EV-rent arrears all follow the person.

See ``DESIGN.md`` for the full rationale behind each table.
"""

from __future__ import annotations

import sqlite3

SCHEMA: str = """
-- ── person_registry ─────────────────────────────────────────────────────────
-- Canonical identity. One row = one real human.
--   kyc_no             : Aadhaar (UNIQUE when present); collected later.
--   deduction_company  : which company file triggers this person's EV rent.
--   deduction_rider_id : which rider_id within that company the rent is logged
--                        against. Moves automatically via cascading logic.
CREATE TABLE IF NOT EXISTS person_registry (
    person_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name       TEXT NOT NULL,
    kyc_no             TEXT UNIQUE,
    deduction_company  TEXT,
    deduction_rider_id TEXT,
    created_at         TEXT DEFAULT (datetime('now'))
);

-- ── rider_master ────────────────────────────────────────────────────────────
-- One row per (rider_id, company). Same person + 2 IDs = 2 rows, one person_id.
-- Each row keeps its own `name`, which preserves aliases after a merge.
CREATE TABLE IF NOT EXISTS rider_master (
    rider_id   TEXT NOT NULL,
    company    TEXT NOT NULL,
    person_id  INTEGER NOT NULL REFERENCES person_registry(person_id),
    name       TEXT,
    hub        TEXT,
    vehicle    TEXT,
    account_no TEXT,
    ifsc       TEXT,
    mob_no     TEXT,
    email      TEXT,
    is_active  INTEGER NOT NULL DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (rider_id, company)
);
CREATE INDEX IF NOT EXISTS idx_rider_person  ON rider_master (person_id);
CREATE INDEX IF NOT EXISTS idx_rider_company ON rider_master (person_id, company);

-- ── ev_models ───────────────────────────────────────────────────────────────
-- Rate card per provider+model. Daily rate is derived as weekly_rate / 7.
CREATE TABLE IF NOT EXISTS ev_models (
    model_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    provider    TEXT NOT NULL,
    model_name  TEXT NOT NULL,
    weekly_rate REAL NOT NULL,
    UNIQUE (provider, model_name)
);

-- ── ev_units ────────────────────────────────────────────────────────────────
-- One row per physical EV. Rate follows the unit's model.
CREATE TABLE IF NOT EXISTS ev_units (
    ev_id    TEXT PRIMARY KEY,
    model_id INTEGER NOT NULL REFERENCES ev_models(model_id),
    status   TEXT NOT NULL DEFAULT 'in_use',   -- in_use | returned | spare
    notes    TEXT
);

-- ── ev_assignments ──────────────────────────────────────────────────────────
-- History of who held which EV and when. The open row (returned_date IS NULL)
-- is the current assignment and is the basis for rent proration.
CREATE TABLE IF NOT EXISTS ev_assignments (
    assignment_id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id     INTEGER NOT NULL REFERENCES person_registry(person_id),
    ev_id         TEXT NOT NULL REFERENCES ev_units(ev_id),
    handover_date TEXT,           -- NULL => rent the full cycle (legacy riders)
    returned_date TEXT,           -- NULL => currently held
    rent_charged_through TEXT,    -- last date EV rent billed through
    created_at    TEXT DEFAULT (datetime('now'))
);
-- At most one open assignment per person.
CREATE UNIQUE INDEX IF NOT EXISTS idx_one_open_assignment
    ON ev_assignments (person_id) WHERE returned_date IS NULL;
CREATE INDEX IF NOT EXISTS idx_assignment_person ON ev_assignments (person_id);
CREATE INDEX IF NOT EXISTS idx_assignment_ev     ON ev_assignments (ev_id);

-- ── ev_arrears ──────────────────────────────────────────────────────────────
-- The arrears tab tracks two independent buckets per person, both kept
-- separate from general dues:
--   * EV-rent arrears  (total_missed / total_recovered / outstanding) — from
--     RENT_MISSED / RENT_RECOVERED transactions.
--   * COD-pending arrears (cod_missed / cod_recovered / cod_outstanding) —
--     from COD_MISSED / COD_RECOVERED transactions. COD that can't be cleared
--     from a payout rolls forward and is clawed back exactly like EV rent.
CREATE TABLE IF NOT EXISTS ev_arrears (
    person_id        INTEGER PRIMARY KEY REFERENCES person_registry(person_id),
    total_missed     REAL NOT NULL DEFAULT 0,
    total_recovered  REAL NOT NULL DEFAULT 0,
    outstanding      REAL NOT NULL DEFAULT 0,
    cod_missed       REAL NOT NULL DEFAULT 0,
    cod_recovered    REAL NOT NULL DEFAULT 0,
    cod_outstanding  REAL NOT NULL DEFAULT 0,
    last_updated     TEXT
);

-- ── transactions ────────────────────────────────────────────────────────────
-- Immutable, append-only audit trail. Never UPDATE/DELETE; corrections are new
-- offsetting rows. amount: positive = credit, negative = debit.
--   event_type: PAYOUT | RENT | RENT_MISSED | RENT_RECOVERED | DUES_CARRY |
--               ADJUSTMENT | DEDUCTION_SWITCH | EV_SWAP | OPENING
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id     INTEGER NOT NULL REFERENCES person_registry(person_id),
    rider_id      TEXT,
    company       TEXT,
    cycle_start   TEXT NOT NULL,
    cycle_end     TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    amount        REAL NOT NULL,
    balance_after REAL NOT NULL,
    days          INTEGER,
    remarks       TEXT,
    created_at    TEXT DEFAULT (datetime('now')),
    created_by    TEXT
);
CREATE INDEX IF NOT EXISTS idx_txn_person_cycle
    ON transactions (person_id, cycle_start, cycle_end);
CREATE INDEX IF NOT EXISTS idx_txn_rent_guard
    ON transactions (person_id, event_type, cycle_start, cycle_end);

-- ── balances ────────────────────────────────────────────────────────────────
-- General rolling balance per person (negative = dues). EV arrears tracked
-- separately in ev_arrears. ``pending_xc_rent`` is a separate slot used for
-- multi-company riders: when one company's payout can't cover the cycle's EV
-- rent, the shortfall sits here (not in current_balance) so the rider's NEXT
-- payout at any other company gets first crack at recovering it. If that
-- attempt also fails, the engine converts the pending amount to ordinary
-- carryforward (i.e., it's drawn from current_balance going forward).
CREATE TABLE IF NOT EXISTS balances (
    person_id          INTEGER PRIMARY KEY REFERENCES person_registry(person_id),
    current_balance    REAL NOT NULL DEFAULT 0,
    pending_xc_rent    REAL NOT NULL DEFAULT 0,
    xc_origin_company  TEXT,
    last_updated       TEXT
);

-- ── cod_holds ───────────────────────────────────────────────────────────────
-- Persisted COD/hold detail per cycle. Per-rider hold total =
-- SUM(amount) for that rider in that cycle. source: jiffy_sheet | myntra_column
CREATE TABLE IF NOT EXISTS cod_holds (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_start  TEXT NOT NULL,
    cycle_end    TEXT NOT NULL,
    company      TEXT NOT NULL,
    rider_id     TEXT,
    person_id    INTEGER REFERENCES person_registry(person_id),
    worker_code  TEXT,
    order_number TEXT,
    amount       REAL NOT NULL DEFAULT 0,
    payment_mode TEXT,
    txn_status   TEXT,
    source       TEXT NOT NULL,
    cleared_at   TEXT,           -- NULL until the operator marks the COD collected
    cleared_by   TEXT,
    created_at   TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_cod_cycle
    ON cod_holds (company, cycle_start, cycle_end, rider_id);

-- ── companies ───────────────────────────────────────────────────────────────
-- Parser configuration. Onboarding a company = a row here (+ a parser).
--   payout_sheet : '0' (index) or 'pattern:<substr>' to match a sheet by name.
--   hold_style   : 'sheet' (separate COD line-item sheet, e.g. Jiffy)
--                | 'column' (inline COD-Pending column, e.g. Myntra) | NULL
CREATE TABLE IF NOT EXISTS companies (
    company_name       TEXT PRIMARY KEY,
    parser_type        TEXT NOT NULL,
    payout_sheet       TEXT,
    rider_id_column    TEXT NOT NULL,
    payout_column      TEXT NOT NULL,
    has_hold_sheet     INTEGER NOT NULL DEFAULT 0,
    hold_style         TEXT,
    hold_sheet         TEXT,
    hold_key_column    TEXT,
    hold_amount_column TEXT,
    hold_status_column TEXT,
    is_active          INTEGER NOT NULL DEFAULT 1
);

-- ── users ───────────────────────────────────────────────────────────────────
-- Login credentials. bcrypt-hashed passwords only.
CREATE TABLE IF NOT EXISTS users (
    email         TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',   -- admin | user
    is_active     INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT DEFAULT (datetime('now'))
);

-- ── status_tracking ─────────────────────────────────────────────────────────
-- Per-person activity. INACTIVE output highlights people with dues or an EV
-- not yet returned.
CREATE TABLE IF NOT EXISTS status_tracking (
    person_id   INTEGER PRIMARY KEY REFERENCES person_registry(person_id),
    status      TEXT NOT NULL DEFAULT 'active',   -- active | inactive
    last_seen   TEXT,
    ev_returned INTEGER NOT NULL DEFAULT 0
);

-- ── ev_maintenance ──────────────────────────────────────────────────────────
-- EV downtime windows. The rent engine excludes any chargeable day that falls
-- inside a window for that EV (auto-applied every cycle).
CREATE TABLE IF NOT EXISTS ev_maintenance (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    ev_id      TEXT NOT NULL REFERENCES ev_units(ev_id),
    from_date  TEXT NOT NULL,
    to_date    TEXT,                  -- NULL = still in maintenance, no return date yet
    reason     TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    created_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_maint_ev ON ev_maintenance (ev_id);
"""


def apply_schema(conn: sqlite3.Connection) -> None:
    """Create all tables and indexes if they do not already exist."""
    conn.executescript(SCHEMA)
