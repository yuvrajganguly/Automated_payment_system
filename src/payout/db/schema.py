"""Database schema (DDL).

One canonical human is a ``person`` with a stable ``person_id``; a person may
hold many ``rider_id``s across and within companies but rents at most one EV at
a time. EV rent, dues, and EV-rent arrears all follow the person.

See ``DESIGN.md`` for the full rationale behind each table.
"""

from __future__ import annotations

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
    weekly_rate INTEGER NOT NULL,
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
    total_missed     INTEGER NOT NULL DEFAULT 0,
    total_recovered  INTEGER NOT NULL DEFAULT 0,
    outstanding      INTEGER NOT NULL DEFAULT 0,
    cod_missed       INTEGER NOT NULL DEFAULT 0,
    cod_recovered    INTEGER NOT NULL DEFAULT 0,
    cod_outstanding  INTEGER NOT NULL DEFAULT 0,
    last_updated     TEXT
);

-- ── transactions ────────────────────────────────────────────────────────────
-- Immutable, append-only audit trail. Never UPDATE/DELETE; corrections are new
-- offsetting rows. amount: positive = credit, negative = debit.
--   event_type: PAYOUT | RENT | RENT_MISSED | RENT_RECOVERED | RENT_REVERSAL |
--               DEPOSIT_APPLIED (security deposit vs debt on EV closure) |
--               DUES_CARRY | ADJUSTMENT | DEDUCTION_SWITCH | EV_SWAP | OPENING
--   (RENT_REVERSAL: arrears written off because a backdated EV return proved
--   the rent should never have been charged — see domain/return_heal.py)
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id     INTEGER NOT NULL REFERENCES person_registry(person_id),
    rider_id      TEXT,
    company       TEXT,
    cycle_start   TEXT NOT NULL,
    cycle_end     TEXT NOT NULL,
    event_type    TEXT NOT NULL,
    amount        INTEGER NOT NULL,
    balance_after INTEGER NOT NULL,
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
    person_id            INTEGER PRIMARY KEY REFERENCES person_registry(person_id),
    current_balance      INTEGER NOT NULL DEFAULT 0,
    pending_xc_rent      INTEGER NOT NULL DEFAULT 0,
    xc_origin_company    TEXT,
    -- cycle_end of the cycle that produced this pending_xc_rent shortfall.
    -- Lets the engine detect "a new cycle's RENT just landed" and collapse
    -- the old pending_xc into general dues before charging fresh rent.
    xc_origin_cycle_end  TEXT,
    last_updated         TEXT
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
    amount       INTEGER NOT NULL DEFAULT 0,
    payment_mode TEXT,
    txn_status   TEXT,
    source       TEXT NOT NULL,
    -- Hub/store code and worker name exactly as the company's COD sheet
    -- states them. A COD rider need not be in the payout (or on the roster),
    -- so the file is the only source for these.
    hub          TEXT,
    worker_name  TEXT,
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
    -- Optional column name in the company file holding the orders/deliveries
    -- count (Spencer's: Delivered Order, Myntra: Total Order Completed, etc.).
    -- Read straight through to the PAY/DUES sheets so payouts show orders.
    orders_column      TEXT,
    has_hold_sheet     INTEGER NOT NULL DEFAULT 0,
    hold_style         TEXT,
    hold_sheet         TEXT,
    hold_key_column    TEXT,
    hold_amount_column TEXT,
    hold_status_column TEXT,
    is_active          INTEGER NOT NULL DEFAULT 1,
    -- Name of another company whose rider IDs this company reuses (Nykaa pays
    -- Blitz riders under their Blitz IDs). An unknown rider_id in this
    -- company's file that exists under that company is linked automatically.
    rider_ids_shared_with TEXT
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

-- ── company_cycles ──────────────────────────────────────────────────────────
-- One row per committed engine run (per company per cycle). Records the
-- headline numbers so dashboards can render cross-company stats without
-- recomputing from transactions every time. ``week_bucket`` is the ISO
-- week derived from cycle_end (YYYY-Www) — group by this column to roll up
-- multiple companies' runs into a "global cycle" for the same calendar week.
CREATE TABLE IF NOT EXISTS company_cycles (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    company              TEXT NOT NULL,
    cycle_start          TEXT NOT NULL,
    cycle_end            TEXT NOT NULL,
    week_bucket          TEXT NOT NULL,
    processed_at         TEXT DEFAULT (datetime('now')),
    processed_by         TEXT,
    rider_count          INTEGER NOT NULL DEFAULT 0,
    riders_paid          INTEGER NOT NULL DEFAULT 0,
    riders_in_dues       INTEGER NOT NULL DEFAULT 0,
    total_release        INTEGER NOT NULL DEFAULT 0,
    total_rent_charged   INTEGER NOT NULL DEFAULT 0,
    total_rent_collected INTEGER NOT NULL DEFAULT 0,
    total_rent_missed    INTEGER NOT NULL DEFAULT 0,
    UNIQUE(company, cycle_start, cycle_end)
);
CREATE INDEX IF NOT EXISTS idx_company_cycles_bucket
    ON company_cycles (week_bucket DESC);

-- ── ev_daily_ledger ─────────────────────────────────────────────────────────
-- Day-level source of truth for "what we owe the EV provider" and "what we
-- collected". One row per (ev_id, day) for every day an EV has existed
-- (in_use, idle, or in maintenance). Populated by the engine on every cycle
-- commit (per-leg expansion) and by EV state changes (assign, return,
-- maintenance close). Provider-agnostic — works for Raft, Blive, or any
-- future provider. See payout/domain/ev_daily.py for the helpers.
CREATE TABLE IF NOT EXISTS ev_daily_ledger (
    ev_id                  TEXT NOT NULL REFERENCES ev_units(ev_id),
    day                    TEXT NOT NULL,                       -- ISO date
    state                  TEXT NOT NULL,                       -- billable | handover_free | return_free | maintenance | unassigned
    assigned_person_id     INTEGER REFERENCES person_registry(person_id),
    daily_cost             INTEGER NOT NULL DEFAULT 0,             -- = weekly_rate / 7 when the day is billable to a rider
    provider_cost          INTEGER NOT NULL DEFAULT 0,             -- always weekly_rate/7 — what we owe the EV provider regardless
    billing_status         TEXT,                                -- billed | missed | recovered | pending | waived
    cycle_event_id         INTEGER,                             -- the RENT / RENT_MISSED row that produced this billing_status
    recovery_event_id      INTEGER,                             -- the RENT_RECOVERED / XC_RENT_RECOVERED row that healed a 'missed' day
    last_updated           TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (ev_id, day)
);
CREATE INDEX IF NOT EXISTS idx_evdaily_day        ON ev_daily_ledger (day);
CREATE INDEX IF NOT EXISTS idx_evdaily_status     ON ev_daily_ledger (billing_status);
CREATE INDEX IF NOT EXISTS idx_evdaily_person_day ON ev_daily_ledger (assigned_person_id, day);


-- ── provider_bills ──────────────────────────────────────────────────────────
-- One row per uploaded provider bill (Raft weekly, Blive monthly, etc.). The
-- parsed lines live in ``provider_bill_lines``. The tally view joins each
-- line against our ``ev_daily_ledger`` for the bill's period to surface
-- discrepancies between the provider's charge and what we computed.
CREATE TABLE IF NOT EXISTS provider_bills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    provider        TEXT NOT NULL,                     -- 'Raft' | 'Blive' | …
    period_start    TEXT NOT NULL,                     -- ISO date inclusive
    period_end      TEXT NOT NULL,                     -- ISO date inclusive
    bill_total      INTEGER NOT NULL DEFAULT 0,           -- sum from the file
    line_count      INTEGER NOT NULL DEFAULT 0,
    file_name       TEXT,
    uploaded_at     TEXT DEFAULT (datetime('now')),
    uploaded_by     TEXT,
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_provider_bills_provider
    ON provider_bills (provider, period_end DESC);

CREATE TABLE IF NOT EXISTS provider_bill_lines (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id         INTEGER NOT NULL REFERENCES provider_bills(id),
    line_no         INTEGER,
    ev_id_raw       TEXT,                              -- as it appeared in the file
    ev_id           TEXT,                              -- normalised; NULL if unmatched
    their_amount    INTEGER NOT NULL DEFAULT 0,
    status_note     TEXT,                              -- last column: maintenance / closed / etc.
    -- Filled when we tally against ev_daily_ledger:
    our_amount      INTEGER,
    discrepancy     INTEGER,                              -- their_amount − our_amount
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_bill_lines_bill ON provider_bill_lines (bill_id);
CREATE INDEX IF NOT EXISTS idx_bill_lines_ev   ON provider_bill_lines (ev_id);

-- ── audit_log ───────────────────────────────────────────────────────────────
-- Every state-changing HTTP request (POST / PATCH / DELETE / PUT) made by an
-- authenticated user is written here. Read by the Creator only — even admins
-- shouldn't see what other admins did to keep peer pressure off the log.
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    at          TEXT DEFAULT (datetime('now')),
    email       TEXT,                 -- NULL for anonymous (e.g. login)
    role        TEXT,
    method      TEXT NOT NULL,
    path        TEXT NOT NULL,
    status_code INTEGER,
    duration_ms INTEGER,
    body_excerpt TEXT,                -- first ~500 chars of the request body
    ip          TEXT
);
CREATE INDEX IF NOT EXISTS idx_audit_email ON audit_log (email);
CREATE INDEX IF NOT EXISTS idx_audit_at    ON audit_log (at DESC);

-- ── password_reset_tokens ───────────────────────────────────────────────────
-- 6-digit OTPs the user enters to reset a forgotten password. Tokens are
-- single-use and expire 10 minutes after issue.
CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL,
    otp_hash   TEXT NOT NULL,             -- bcrypt of the 6 digits
    expires_at TEXT NOT NULL,
    used_at    TEXT,                      -- NULL until the OTP is consumed
    attempts   INTEGER NOT NULL DEFAULT 0, -- wrong guesses; locked after MAX_OTP_ATTEMPTS
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_pwd_reset_email ON password_reset_tokens (email);

-- ── status_tracking ─────────────────────────────────────────────────────────
-- Per-person activity. INACTIVE output highlights people with dues or an EV
-- not yet returned.
CREATE TABLE IF NOT EXISTS status_tracking (
    person_id   INTEGER PRIMARY KEY REFERENCES person_registry(person_id),
    status      TEXT NOT NULL DEFAULT 'active',   -- active | inactive
    last_seen   TEXT,
    ev_returned INTEGER NOT NULL DEFAULT 0
);

-- ── payment_uploads ─────────────────────────────────────────────────────────
-- One row per uploaded bank MIS report. Each upload is parsed into multiple
-- payment_lines, each of which is matched against the rider roster and then
-- resolved (success → no action; failed → either marked paid via UPI or the
-- amount is credited back to the rider's ledger).
CREATE TABLE IF NOT EXISTS payment_uploads (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    file_name    TEXT NOT NULL,
    uploaded_at  TEXT DEFAULT (datetime('now')),
    uploaded_by  TEXT,
    line_count   INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    unmatched_count INTEGER NOT NULL DEFAULT 0,
    notes        TEXT
);

-- ── payment_lines ───────────────────────────────────────────────────────────
-- One row per beneficiary line in a MIS report.
--   bank_status        : 'Success' | 'Failed' | 'Rejected' | other (as parsed)
--   match_status       : 'matched' (joined to a person via account+ifsc) |
--                        'name_matched' (joined via fuzzy name) |
--                        'unmatched' (no roster hit)
--   resolution_method  : NULL until operator acts. Then one of:
--                          'bank_ok'        — successful bank transfer, nothing to do
--                          'upi_paid'       — operator paid the rider via UPI QR
--                          'credit_ledger'  — failed and money added back to balance
CREATE TABLE IF NOT EXISTS payment_lines (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    upload_id        INTEGER NOT NULL REFERENCES payment_uploads(id) ON DELETE CASCADE,
    line_no          INTEGER,
    pymt_mode        TEXT,
    bene_name        TEXT,
    bene_account_no  TEXT,
    bene_ifsc        TEXT,
    amount           INTEGER NOT NULL DEFAULT 0,
    remark           TEXT,
    pymt_date        TEXT,
    bank_status      TEXT,
    utr              TEXT,
    customer_ref     TEXT,
    person_id        INTEGER REFERENCES person_registry(person_id),
    matched_name     TEXT,
    match_status     TEXT NOT NULL DEFAULT 'unmatched',
    resolution_method TEXT,
    resolved_at      TEXT,
    resolved_by      TEXT,
    transaction_id   INTEGER REFERENCES transactions(id)
);
CREATE INDEX IF NOT EXISTS idx_pl_upload ON payment_lines (upload_id);
CREATE INDEX IF NOT EXISTS idx_pl_person ON payment_lines (person_id);

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
"""  # noqa: E501


def apply_schema(conn) -> None:
    """Create all tables and indexes if they do not already exist.

    On Postgres the SQLite DDL is translated first (identity columns, BIGINT,
    datetime defaults); on SQLite it runs verbatim.
    """
    from payout.config import DB_URL

    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(SCHEMA))
    else:
        conn.executescript(SCHEMA)
