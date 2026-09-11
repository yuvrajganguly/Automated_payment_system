"""Versioned, backend-neutral schema migrations.

Why this exists
---------------
``apply_schema`` is ``CREATE TABLE IF NOT EXISTS`` — a no-op on tables that
already exist — and the old ``_migrate`` hook was SQLite-only (``PRAGMA
table_info`` + ``ALTER TABLE``) and returned early on Postgres. So the first
column added after the Postgres cutover would pass CI (which recreates the
schema per test) and crash production with "column does not exist".

How it works
------------
* ``MIGRATIONS`` is an ordered list of ``(name, fn)``. Names are numbered and
  never renamed once shipped. Each ``fn`` receives a connection and must be
  **idempotent** (use the ``add_column`` / ``has_column`` helpers).
* Applied names are recorded in ``schema_migrations``.
* On a **fresh** database (no core tables before ``apply_schema`` ran) every
  migration is recorded as applied without running — ``SCHEMA`` already
  describes the latest shape.
* On a **pre-existing** database that has never seen this runner, the legacy
  SQLite hook is run once to reach the ``0001_baseline`` state, the baseline
  is recorded, and everything after it runs.
* Otherwise only the pending migrations run.

Adding a migration
------------------
1. Change ``SCHEMA`` in ``schema.py`` so fresh databases get the new shape.
2. Append ``("000N_short_name", fn)`` to ``MIGRATIONS`` that brings an existing
   database to that same shape. Keep it idempotent.
3. Run the test suite on both backends (``pytest`` and ``PAYOUT_DB_URL=... pytest``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from payout.config import DB_URL

# ─────────────────────────── introspection helpers ───────────────────────────


def table_exists(conn: Any, table: str) -> bool:
    if DB_URL:
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_name = ?",
            (table,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone()
    return row is not None


def has_column(conn: Any, table: str, column: str) -> bool:
    if DB_URL:
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = ? AND column_name = ?",
            (table, column),
        ).fetchone()
        return row is not None
    cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    return column in cols


def add_column(conn: Any, table: str, column: str, ddl: str) -> bool:
    """``ALTER TABLE table ADD COLUMN column ddl`` if the column is missing.

    ``ddl`` is the SQLite-dialect type + constraints (``TEXT``, ``INTEGER NOT
    NULL DEFAULT 0``). Both backends accept these spellings for the simple
    cases we use. Returns True when the column was added.
    """
    if has_column(conn, table, column):
        return False
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    return True


# ────────────────────────────── the migrations ───────────────────────────────


def _baseline(conn: Any) -> None:
    """Everything that existed in SCHEMA when the runner was introduced."""


def _0002_reset_token_attempts(conn: Any) -> None:
    """Count wrong OTP guesses so a reset code can be locked after a few."""
    add_column(conn, "password_reset_tokens", "attempts", "INTEGER NOT NULL DEFAULT 0")


def _0003_companies_shared_rider_ids(conn: Any) -> None:
    """A company can declare that its rider IDs are the same IDs another
    company issues (Nykaa uses Blitz's rider IDs). The engine then links an
    unknown rider automatically instead of flagging it."""
    add_column(conn, "companies", "rider_ids_shared_with", "TEXT")


def _0004_offset_credit_vs_arrears(conn: Any) -> None:
    """Data sweep: riders holding BOTH a credit balance and EV-rent arrears
    owed nothing net, but both sides sat on the books forever unless another
    payout cycle happened to run for them. Settle every overlap once; the
    routes that create credits now do this at write time."""
    from payout.domain.arrears import settle_arrears_from_credit

    rows = conn.execute(
        "SELECT b.person_id FROM balances b JOIN ev_arrears ea ON ea.person_id = b.person_id "
        "WHERE b.current_balance > 0 AND ea.outstanding > 0"
    ).fetchall()
    for r in rows:
        settle_arrears_from_credit(conn, r[0], created_by="migration:0004_offset_credit_vs_arrears")


def _0005_deposit_for_closed_evs(conn: Any) -> None:
    """Every EV rider placed a security deposit. Riders who already CLOSED
    their EV (no open assignment) with debt still on the books never had it
    applied — sweep them once: up to the deposit cap comes off EV back-rent,
    then carried dues. New closures apply it at return time in the routes."""
    from payout.domain.arrears import settle_from_deposit

    rows = conn.execute(
        "SELECT DISTINCT a.person_id FROM ev_assignments a "
        "LEFT JOIN (SELECT DISTINCT person_id FROM ev_assignments "
        "           WHERE returned_date IS NULL) o ON o.person_id = a.person_id "
        "LEFT JOIN ev_arrears ea ON ea.person_id = a.person_id "
        "LEFT JOIN balances b ON b.person_id = a.person_id "
        "WHERE a.returned_date IS NOT NULL AND o.person_id IS NULL "
        "  AND (COALESCE(ea.outstanding, 0) > 0 OR COALESCE(b.current_balance, 0) < 0)"
    ).fetchall()
    for r in rows:
        settle_from_deposit(conn, r[0], created_by="migration:0005_deposit_for_closed_evs")


def _0006_collapse_bluedart(conn: Any) -> None:
    """Fold the retired Blue Dart module into the central model.

    Blue Dart lived on an unmerged branch as a salaried side-module
    (bluedart_riders / bluedart_attendance / bluedart_ev) whose riders were
    never charged EV rent. Decision (2026-09-02): the section is retired;
    its ACTIVE riders and their EV holdings become ordinary central records
    and rent is chargeable from 2026-09-01.

    For every active bluedart_rider:
      * a rider_master row under company 'BlueDart' (their BD code, or a
        BD-<id> placeholder), reusing the already-linked person;
      * their person's deduction anchor set to BlueDart ONLY if they have
        no anchor yet (multi-company riders keep their existing anchor);
      * their OPEN bluedart_ev holding becomes an ev_assignments row —
        original handover preserved, rent meter set to 2026-08-31 so
        billing starts 1 Sept; the bluedart_ev row is closed 2026-08-31
        with a migration note, and the unit is marked in_use.
    Rows that would violate the one-open-assignment / one-holder rules are
    skipped (books already disagree; the operator resolves those by hand).
    Attendance/payroll history stays in the bluedart_* tables, read-only.
    Fresh databases (no bluedart tables) skip this entirely.
    """
    if not table_exists(conn, "bluedart_riders"):
        return
    conn.execute(
        "INSERT OR IGNORE INTO companies (company_name, parser_type, rider_id_column, "
        "payout_column) VALUES ('BlueDart', 'generic', 'rider_id', 'net_pay')"
    )
    riders = conn.execute(
        "SELECT id, person_id, bd_rider_id, name, hub, mob_no, account_no, ifsc "
        "FROM bluedart_riders WHERE is_active = 1"
    ).fetchall()
    for r in riders:
        rid = (r["bd_rider_id"] or f"BD-{r['id']}").strip()
        if not conn.execute(
            "SELECT 1 FROM rider_master WHERE rider_id=? AND company='BlueDart'", (rid,)
        ).fetchone():
            conn.execute(
                "INSERT INTO rider_master (rider_id, company, person_id, name, hub, "
                "vehicle, account_no, ifsc, mob_no, is_active) "
                "VALUES (?, 'BlueDart', ?, ?, ?, 'EV', ?, ?, ?, 1)",
                (rid, r["person_id"], r["name"], r["hub"], r["account_no"], r["ifsc"], r["mob_no"]),
            )
        conn.execute(
            "UPDATE person_registry SET deduction_company='BlueDart', deduction_rider_id=? "
            "WHERE person_id=? AND (deduction_company IS NULL OR deduction_company='')",
            (rid, r["person_id"]),
        )
        holding = conn.execute(
            "SELECT id, ev_id, handover_date FROM bluedart_ev "
            "WHERE bd_rider_id=? AND returned_date IS NULL",
            (r["id"],),
        ).fetchone()
        if not holding:
            continue
        person_busy = conn.execute(
            "SELECT 1 FROM ev_assignments WHERE person_id=? AND returned_date IS NULL",
            (r["person_id"],),
        ).fetchone()
        ev_busy = conn.execute(
            "SELECT 1 FROM ev_assignments WHERE ev_id=? AND returned_date IS NULL",
            (holding["ev_id"],),
        ).fetchone()
        if person_busy or ev_busy:
            continue  # books already disagree — leave for the operator
        conn.execute(
            "INSERT INTO ev_assignments (person_id, ev_id, handover_date, "
            "rent_charged_through) VALUES (?, ?, ?, '2026-08-31')",
            (r["person_id"], holding["ev_id"], holding["handover_date"]),
        )
        conn.execute("UPDATE ev_units SET status='in_use' WHERE ev_id=?", (holding["ev_id"],))
        conn.execute(
            "UPDATE bluedart_ev SET returned_date='2026-08-31', "
            "notes=COALESCE(notes,'') || ' [migrated to central ev_assignments 2026-09-01]' "
            "WHERE id=?",
            (holding["id"],),
        )


def _0007_cod_hub_and_spencers_layout(conn: Any) -> None:
    """Spencer's 2026-08 payout layout + COD hub/name.

    * ``cod_holds.hub`` / ``worker_name``: the COD sheet's HUB CODE and WORKER
      NAME, so the HOLD sheet can label COD riders who are not in the payout.
    * Spencer's file now keys riders on ``rider_phone`` (the rider id has
      always been the phone number), pays ``Total Payable`` and counts
      ``total_orders_delivered``. Column configs accept ``|``-separated
      alternatives, so both the old and the new headers stay valid. Only a
      config still on the stock value is touched — an operator's edit wins.
    """
    add_column(conn, "cod_holds", "hub", "TEXT")
    add_column(conn, "cod_holds", "worker_name", "TEXT")
    for col, old, new in (
        ("rider_id_column", "Rider id", "Rider id|rider_phone"),
        ("payout_column", "Total Payable Amount", "Total Payable Amount|Total Payable"),
        ("orders_column", "Delivered Orders", "Delivered Orders|total_orders_delivered"),
    ):
        # Company name bound as a parameter: a double-quoted "Spencer's" would
        # be an identifier on Postgres, not a string. Both the old and the new
        # name are matched — migration 0024 renamed this client to Jiffy, and a
        # config repair should not be defeated by a later rename.
        conn.execute(
            f"UPDATE companies SET {col}=? WHERE company_name IN (?, ?) AND {col}=?",
            (new, "Spencer's", "Jiffy", old),
        )


def _0008_cod_hub_code(conn: Any) -> None:
    """``cod_holds.hub`` now holds the hub NAME (resolved through the new
    ``hub_codes`` table, created by apply_schema); the code the COD sheet
    stated moves to ``hub_code``. Rows written before this carry the raw code
    in ``hub`` — copy it across so nothing is lost."""
    if add_column(conn, "cod_holds", "hub_code", "TEXT"):
        conn.execute("UPDATE cod_holds SET hub_code = hub WHERE hub_code IS NULL")


def _0009_suspected_return_dismissals(conn: Any) -> None:
    """Operators can now mark a suspected EV return as 'not a return'
    (rider absent / sponsored EV). New table; apply_schema creates it for
    fresh databases, this creates it for existing ones."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS suspected_return_dismissals ("
        "  assignment_id      INTEGER PRIMARY KEY REFERENCES ev_assignments(assignment_id),"
        "  kind               TEXT NOT NULL,"
        "  reason             TEXT NOT NULL,"
        "  missed_cycles_then INTEGER NOT NULL DEFAULT 0,"
        "  dismissed_by       TEXT,"
        "  dismissed_at       TEXT DEFAULT (datetime('now'))"
        ")"
    )


def _0010_users_phone(conn: Any) -> None:
    """Users can sign in with a phone number as well as an email."""
    add_column(conn, "users", "phone", "TEXT")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_phone ON users (phone) WHERE phone IS NOT NULL"
    )


def _0011_collapse_raft_warrior_models(conn: Any) -> None:
    """Raft's WARRIOR and WARRIOR 2.0 are the Regular model at the same
    rate; three names for one thing only cluttered the rate card. Units move
    to Regular and the two rows go. A WARRIOR row with a *different* rate is
    left alone (the operator decides), so nobody's rent changes silently."""
    if not table_exists(conn, "ev_models"):
        return
    regular = conn.execute(
        "SELECT model_id, weekly_rate FROM ev_models "
        "WHERE provider='Raft' AND LOWER(model_name)='regular'"
    ).fetchone()
    if not regular:
        return
    for row in conn.execute(
        "SELECT model_id, model_name, weekly_rate FROM ev_models "
        "WHERE provider='Raft' AND LOWER(model_name) LIKE 'warrior%'"
    ).fetchall():
        if int(row["weekly_rate"]) != int(regular["weekly_rate"]):
            print(
                f"[migrate] leaving Raft {row['model_name']!r}: rate {row['weekly_rate']} "
                f"differs from Regular {regular['weekly_rate']}"
            )
            continue
        conn.execute(
            "UPDATE ev_units SET model_id=? WHERE model_id=?",
            (regular["model_id"], row["model_id"]),
        )
        conn.execute("DELETE FROM ev_models WHERE model_id=?", (row["model_id"],))


def _0012_person_identity_numbers(conn: Any) -> None:
    """Aadhaar and PAN numbers on the person (numbers only — scans were
    judged too messy to keep; 2026-09-05)."""
    add_column(conn, "person_registry", "aadhaar_no", "TEXT")
    add_column(conn, "person_registry", "pan_no", "TEXT")


def _0013_company_payment_model(conn: Any) -> None:
    """How each company pays, so the office can onboard a company without a
    parser (2026-09-05): ``payment_model`` payout_file | per_order | direct,
    ``cadence`` weekly | monthly | slots, ``per_order_rate`` (paise), ``notes``.
    Spencer's is the one slots company; everything existing sends a file."""
    add_column(conn, "companies", "payment_model", "TEXT NOT NULL DEFAULT 'payout_file'")
    add_column(conn, "companies", "cadence", "TEXT NOT NULL DEFAULT 'weekly'")
    add_column(conn, "companies", "per_order_rate", "INTEGER")
    add_column(conn, "companies", "notes", "TEXT")
    conn.execute("UPDATE companies SET cadence='slots' WHERE company_name=?", ("Spencer's",))


def _0014_seed_direct_and_per_order_companies(conn: Any) -> None:
    """Zomato and Flipkart pay riders directly; Shadowfax has no file — the
    office reads the order count off their dashboard and pays ₹15 an order.
    Only inserted when the name is absent, so a row edited in the UI stays."""
    rows = [
        ("Zomato", "direct", None, "Pays riders directly. Roster only — no payout file."),
        (
            "Shadowfax",
            "per_order",
            1500,
            "No payout file. Order counts come from the Shadowfax dashboard; "
            "₹15 per order paid by us.",
        ),
        (
            "Flipkart",
            "direct",
            None,
            "Salary based — details not settled yet; assumed to pay riders directly.",
        ),
    ]
    for name, model, rate, note in rows:
        if conn.execute(
            "SELECT 1 FROM companies WHERE LOWER(company_name)=LOWER(?)", (name,)
        ).fetchone():
            continue
        conn.execute(
            "INSERT INTO companies (company_name, parser_type, payout_sheet, rider_id_column, "
            " payout_column, orders_column, has_hold_sheet, is_active, payment_model, cadence, "
            " per_order_rate, notes) "
            "VALUES (?, ?, NULL, 'rider_id', 'payout', 'orders', 0, 1, ?, 'weekly', ?, ?)",
            (name, "none" if model == "direct" else "orders", model, rate, note),
        )


def _0015_salary_model(conn: Any) -> None:
    """Salaried companies (2026-09-05, replacing the retired Blue Dart module):
    a salary per cycle on the rider row, expected days + incentives on the
    company, and salary_inputs to keep what was marked each cycle."""
    add_column(conn, "companies", "salary_expected_days", "INTEGER NOT NULL DEFAULT 26")
    add_column(conn, "companies", "incentive_per_order", "INTEGER NOT NULL DEFAULT 0")
    add_column(conn, "companies", "incentive_per_day", "INTEGER NOT NULL DEFAULT 0")
    add_column(conn, "rider_master", "salary", "INTEGER")
    ddl = (
        "CREATE TABLE IF NOT EXISTS salary_inputs ("
        "  id           INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  company      TEXT NOT NULL,"
        "  cycle_start  TEXT NOT NULL,"
        "  cycle_end    TEXT NOT NULL,"
        "  rider_id     TEXT NOT NULL,"
        "  person_id    INTEGER,"
        "  days_present REAL NOT NULL DEFAULT 0,"
        "  orders       REAL NOT NULL DEFAULT 0,"
        "  salary       INTEGER NOT NULL DEFAULT 0,"
        "  base_pay     INTEGER NOT NULL DEFAULT 0,"
        "  incentives   INTEGER NOT NULL DEFAULT 0,"
        "  payout       INTEGER NOT NULL DEFAULT 0,"
        "  created_at   TEXT DEFAULT (datetime('now')),"
        "  created_by   TEXT"
        ")"
    )
    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(ddl))
    else:
        conn.execute(ddl)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_salary_inputs_cycle "
        "ON salary_inputs (company, cycle_start, cycle_end)"
    )


def _0016_pidge_delhivery_retire_bluedart_dealshare(conn: Any) -> None:
    """Pidge and Delhivery join as direct-pay companies; Blue Dart and
    Dealshare are switched off (2026-09-05). Deactivating keeps every rider
    row and cycle readable — nothing is deleted."""
    for name in ("Pidge", "Delhivery"):
        if conn.execute(
            "SELECT 1 FROM companies WHERE LOWER(company_name)=LOWER(?)", (name,)
        ).fetchone():
            continue
        conn.execute(
            "INSERT INTO companies (company_name, parser_type, payout_sheet, rider_id_column, "
            " payout_column, orders_column, has_hold_sheet, is_active, payment_model, cadence, "
            " per_order_rate, notes) "
            "VALUES (?, 'none', NULL, 'rider_id', 'payout', 'orders', 0, 1, 'direct', 'weekly', "
            " NULL, 'Pays riders directly (for now). Roster only — no payout file.')",
            (name,),
        )
    conn.execute(
        "UPDATE companies SET is_active=0 WHERE LOWER(company_name) IN ('bluedart', 'dealshare')"
    )


def _0017_refresh_tokens(conn: Any) -> None:
    """Refresh tokens for the recruiter app's long-lived sessions
    (2026-09-06). Mirrors the table in schema.py."""
    ddl = (
        "CREATE TABLE IF NOT EXISTS refresh_tokens ("
        "  id            INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  token_hash    TEXT NOT NULL UNIQUE,"
        "  email         TEXT NOT NULL,"
        "  client        TEXT,"
        "  created_at    TEXT DEFAULT (datetime('now')),"
        "  last_used_at  TEXT,"
        "  expires_at    TEXT NOT NULL,"
        "  revoked_at    TEXT,"
        "  revoke_reason TEXT,"
        "  replaced_by   INTEGER"
        ")"
    )
    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(ddl))
    else:
        conn.execute(ddl)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_refresh_tokens_email ON refresh_tokens (email)")


def _0018_recruiter_app_fields(conn: Any) -> None:
    """Recruiter app, day 2 (2026-09-07): where an action happened
    (activity_log.lat/lng/accuracy_m), who onboarded a rider
    (rider_master.recruited_by — backfilled from the activity log's
    rider.create rows), stores per company with their zone and pay figures
    (company_hubs), and which zone a recruiter works (users.zone) so the
    app's to-do list opens on their stores."""
    add_column(conn, "activity_log", "lat", "REAL")
    add_column(conn, "activity_log", "lng", "REAL")
    add_column(conn, "activity_log", "accuracy_m", "REAL")
    add_column(conn, "rider_master", "recruited_by", "TEXT")
    add_column(conn, "users", "zone", "TEXT")
    ddl = (
        "CREATE TABLE IF NOT EXISTS company_hubs ("
        "  company             TEXT NOT NULL,"
        "  hub                 TEXT NOT NULL,"
        "  zone                TEXT,"
        "  per_order_rate      INTEGER,"
        "  salary              INTEGER,"
        "  incentive_per_order INTEGER,"
        "  incentive_per_day   INTEGER,"
        "  notes               TEXT,"
        "  is_active           INTEGER NOT NULL DEFAULT 1,"
        "  updated_at          TEXT DEFAULT (datetime('now')),"
        "  updated_by          TEXT,"
        "  PRIMARY KEY (company, hub)"
        ")"
    )
    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(ddl))
    else:
        conn.execute(ddl)
    # Every store already on the roster gets a row (zone unassigned).
    for r in conn.execute(
        "SELECT DISTINCT company, hub FROM rider_master WHERE hub IS NOT NULL AND hub<>''"
    ).fetchall():
        if not conn.execute(
            "SELECT 1 FROM company_hubs WHERE company=? AND hub=?", (r["company"], r["hub"])
        ).fetchone():
            conn.execute(
                "INSERT INTO company_hubs (company, hub) VALUES (?,?)", (r["company"], r["hub"])
            )
    # Backfill: the operator who created a rider row is its recruiter.
    for r in conn.execute(
        "SELECT entity_id, email FROM activity_log WHERE action='rider.create' "
        "AND entity_type='rider' ORDER BY id"
    ).fetchall():
        rid, _, co = str(r["entity_id"]).rpartition("@")
        if not rid or not co:
            continue
        conn.execute(
            "UPDATE rider_master SET recruited_by=? WHERE rider_id=? AND company=? "
            "AND recruited_by IS NULL",
            (r["email"], rid, co),
        )


def _0019_recruiter_locations(conn: Any) -> None:
    """Recruiter app "Option 1" tracking (2026-09-07): one location row per
    app open, at most one per 30 minutes, nothing in the background."""
    ddl = (
        "CREATE TABLE IF NOT EXISTS recruiter_locations ("
        "  id         INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  email      TEXT NOT NULL,"
        "  at         TEXT DEFAULT (datetime('now')),"
        "  lat        REAL NOT NULL,"
        "  lng        REAL NOT NULL,"
        "  accuracy_m REAL,"
        "  area       TEXT,"
        "  source     TEXT DEFAULT 'app_open'"
        ")"
    )
    idx = (
        "CREATE INDEX IF NOT EXISTS idx_recruiter_locations_email "
        "ON recruiter_locations (email, at DESC)"
    )
    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(ddl))
        conn.executescript(translate_ddl(idx))
    else:
        conn.execute(ddl)
        conn.execute(idx)


def _0020_ev_closeouts(conn: Any) -> None:
    """EV close-out (2026-09-07): when an EV closes the admin says whether the
    security deposit went back to the rider, and if not, what it covered
    (rent, damage) and what is left. Until then the assignment is
    closeout_pending. Closures before this migration were settled by the old
    automatic rule (0005 + return-time application) and stay as they are."""
    add_column(conn, "ev_assignments", "closeout_pending", "INTEGER NOT NULL DEFAULT 0")
    ddl = (
        "CREATE TABLE IF NOT EXISTS ev_closeouts ("
        "  assignment_id   INTEGER PRIMARY KEY REFERENCES ev_assignments(assignment_id),"
        "  ev_id           TEXT NOT NULL,"
        "  person_id       INTEGER NOT NULL REFERENCES person_registry(person_id),"
        "  sd_returned     INTEGER NOT NULL DEFAULT 0,"
        "  sd_amount       INTEGER NOT NULL DEFAULT 0,"
        "  damage_charges  INTEGER NOT NULL DEFAULT 0,"
        "  rent_charges    INTEGER NOT NULL DEFAULT 0,"
        "  rent_applied    INTEGER NOT NULL DEFAULT 0,"
        "  refund_due      INTEGER NOT NULL DEFAULT 0,"
        "  refund_mode     TEXT,"
        "  shortfall       INTEGER NOT NULL DEFAULT 0,"
        "  note            TEXT,"
        "  created_by      TEXT,"
        "  created_at      TEXT DEFAULT (datetime('now'))"
        ")"
    )
    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(ddl))
    else:
        conn.execute(ddl)


def _0021_referrals(conn: Any) -> None:
    """Rider referrals (2026-09-07): ₹1,000 to the referrer in two ₹500
    instalments once the new rider has worked four weeks."""
    ddl = (
        "CREATE TABLE IF NOT EXISTS referrals ("
        "  id                   INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  new_person_id        INTEGER NOT NULL UNIQUE REFERENCES person_registry(person_id),"
        "  referrer_person_id   INTEGER NOT NULL REFERENCES person_registry(person_id),"
        "  company              TEXT,"
        "  created_by           TEXT,"
        "  created_at           TEXT DEFAULT (datetime('now')),"
        "  qualified_on         TEXT,"
        "  installments_paid    INTEGER NOT NULL DEFAULT 0,"
        "  last_paid_cycle_end  TEXT,"
        "  status               TEXT NOT NULL DEFAULT 'open',"
        "  note                 TEXT"
        ")"
    )
    idx = (
        "CREATE INDEX IF NOT EXISTS idx_referrals_referrer "
        "ON referrals (referrer_person_id, status)"
    )
    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(ddl))
        conn.executescript(translate_ddl(idx))
    else:
        conn.execute(ddl)
        conn.execute(idx)


def _0022_ev_requests(conn: Any) -> None:
    """EV requests (2026-09-07): a recruiter asking the fleet desk for N EVs
    for a store. A queue, not money — nothing here touches the ledger."""
    ddl = (
        "CREATE TABLE IF NOT EXISTS ev_requests ("
        "  id                 INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  created_at         TEXT DEFAULT (datetime('now')),"
        "  created_by         TEXT NOT NULL,"
        "  quantity           INTEGER NOT NULL,"
        "  hub                TEXT,"
        "  company            TEXT,"
        "  zone               TEXT,"
        "  note               TEXT,"
        "  status             TEXT NOT NULL DEFAULT 'open',"
        "  fulfilled_quantity INTEGER,"
        "  resolved_by        TEXT,"
        "  resolved_at        TEXT,"
        "  resolution_note    TEXT"
        ")"
    )
    idx = (
        "CREATE INDEX IF NOT EXISTS idx_ev_requests_status ON ev_requests (status, created_at DESC)"
    )
    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(ddl))
        conn.executescript(translate_ddl(idx))
    else:
        conn.execute(ddl)
        conn.execute(idx)


def _0023_app_crashes(conn: Any) -> None:
    """Crash reports posted by the recruiter app (2026-09-07): an app that dies
    on launch has no logcat anyone can read, so it sends its own last breath."""
    ddl = (
        "CREATE TABLE IF NOT EXISTS app_crashes ("
        "  id      INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  at      TEXT DEFAULT (datetime('now')),"
        "  version TEXT,"
        "  device  TEXT,"
        "  android TEXT,"
        "  kind    TEXT NOT NULL DEFAULT 'crash',"
        "  email   TEXT,"
        "  trail   TEXT,"
        "  detail  TEXT"
        ")"
    )
    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(ddl))
    else:
        conn.execute(ddl)


COMPANY_RENAMES_2026_09: tuple[tuple[str, str], ...] = (
    ("Flipkart", "Elastic"),
    ("Spencer's", "Jiffy"),
    ("Blitz", "Kaptan"),
)


def _0024_rename_companies(conn: Any) -> None:
    """Three clients renamed (2026-09-08): Flipkart→Elastic, Spencer's→Jiffy,
    Blitz→Kaptan.

    ``companies.company_name`` is the primary key and there is no surrogate id,
    so the name is copied verbatim into a dozen other tables — including the
    append-only ledger and the activity feed. The owner asked for the rename to
    reach history too: one name, one truth, no legacy label surviving in old
    payout rows. ``rename_company`` walks ``COMPANY_REFS`` and does the lot in
    this migration's transaction.

    Idempotent by construction: a rename whose source is gone or whose target
    already exists changes nothing, so re-running is a no-op. A database that
    was seeded fresh after this release already carries the new names and skips
    every pair here.
    """
    from payout.db.references import rename_company

    for old, new in COMPANY_RENAMES_2026_09:
        rename_company(conn, old, new)


def _0025_recruiter_profiles(conn: Any) -> None:
    """A recruiter's own profile (2026-09-08): display name, bank details and
    identity numbers, kept off ``users`` so a row of login credentials never
    carries PII beside the password hash.

    Aadhaar and PAN are stored as entered — the rider-side columns on
    ``person_registry`` already work that way and a second scheme would be
    worse than one consistent one — but unlike the rider fields these are
    masked on every response except the recruiter's own profile and an
    admin's view of it. ``photo_key`` points into the same document store the
    rider photos use.
    """
    add_column(conn, "users", "display_name", "TEXT")
    ddl = (
        "CREATE TABLE IF NOT EXISTS recruiter_profiles ("
        "  email        TEXT PRIMARY KEY,"
        "  full_name    TEXT,"
        "  phone        TEXT,"
        "  address      TEXT,"
        "  account_name TEXT,"
        "  account_no   TEXT,"
        "  ifsc         TEXT,"
        "  bank_name    TEXT,"
        "  aadhaar_no   TEXT,"
        "  pan_no       TEXT,"
        "  photo_key    TEXT,"
        "  updated_at   TEXT DEFAULT (datetime('now'))"
        ")"
    )
    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(ddl))
    else:
        conn.execute(ddl)


def _0026_ev_assignment_actor(conn: Any) -> None:
    """Who handed the EV over (2026-09-08).

    ``ev_assignments`` recorded the rider and the dates but never the person
    who performed the handover — that only existed in ``activity_log``, which
    made "how many EVs did this recruiter deploy" a string-matching query over
    a feed table. Two columns, backfilled from the feed so history is not lost.
    """
    add_column(conn, "ev_assignments", "assigned_by", "TEXT")
    add_column(conn, "ev_assignments", "returned_by", "TEXT")
    if not table_exists(conn, "activity_log"):
        return
    # The feed keys EV rows by ev_id; pair each assignment with the closest
    # preceding log row for the same unit. Ties and gaps simply stay NULL.
    for action, col, date_col in (
        ("ev.assign", "assigned_by", "handover_date"),
        ("ev.return", "returned_by", "returned_date"),
    ):
        conn.execute(
            f"UPDATE ev_assignments SET {col} = ("  # noqa: S608 - names are literals above
            "  SELECT a.email FROM activity_log a"
            "  WHERE a.entity_type='ev' AND a.action=?"
            "    AND a.entity_id = ev_assignments.ev_id"
            "    AND SUBSTR(a.at, 1, 10) = SUBSTR(ev_assignments." + date_col + ", 1, 10)"
            "  ORDER BY a.id LIMIT 1"
            f") WHERE {col} IS NULL AND {date_col} IS NOT NULL",
            (action,),
        )


def _0027_recruiter_shifts(conn: Any) -> None:
    """Odometer readings per recruiter per day (2026-09-08).

    A recruiter types the vehicle's reading at the start of the shift and again
    at the end, photographing the dash both times; the day's distance is
    ``end_km - start_km`` and the month's total is what the fuel claim is paid
    on. Readings are whole kilometres — that is what a dash shows, and it is
    one less thing to mistype on a phone.

    One row per (email, day): re-saving a start reading corrects it rather than
    adding a second row. The photos are the evidence behind the claim, so the
    row keeps both keys and the timestamps at which each half was recorded.
    """
    ddl = (
        "CREATE TABLE IF NOT EXISTS recruiter_shifts ("
        "  id              INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  email           TEXT NOT NULL,"
        "  day             TEXT NOT NULL,"  # YYYY-MM-DD, the recruiter's local day
        "  start_km        INTEGER,"
        "  start_photo_key TEXT,"
        "  start_at        TEXT,"
        "  end_km          INTEGER,"
        "  end_photo_key   TEXT,"
        "  end_at          TEXT,"
        "  note            TEXT,"
        "  created_at      TEXT DEFAULT (datetime('now'))"
        ")"
    )
    idx = (
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_recruiter_shift_day ON recruiter_shifts (email, day)"
    )
    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(ddl))
        conn.executescript(translate_ddl(idx))
    else:
        conn.execute(ddl)
        conn.execute(idx)


def _0028_ev_closeout_reports(conn: Any) -> None:
    """What the recruiter saw when the EV came back (2026-09-08).

    The close-out itself is a money decision — the deposit is cleared against
    arrears and dues, the leftover is credited or refunded, the excess becomes
    debt — and that stays with an admin. But the person who actually knows
    whether the deposit went back in cash, and whether the vehicle came back
    damaged, is the recruiter standing in the hub with it.

    So the two are separated. This table is the field report: an observation,
    written by whoever took the EV back, that moves no money. The admin's
    close-out form opens pre-filled from it, and ``ev_closeouts`` remains the
    only place a rupee changes hands.
    """
    ddl = (
        "CREATE TABLE IF NOT EXISTS ev_closeout_reports ("
        "  assignment_id  INTEGER PRIMARY KEY,"
        "  ev_id          TEXT NOT NULL,"
        "  person_id      INTEGER NOT NULL,"
        "  sd_returned    INTEGER NOT NULL DEFAULT 0,"
        "  damage_charges INTEGER NOT NULL DEFAULT 0,"  # paise, as observed
        "  damage_note    TEXT,"
        "  photo_key      TEXT,"
        "  reported_by    TEXT NOT NULL,"
        "  reported_at    TEXT DEFAULT (datetime('now'))"
        ")"
    )
    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(ddl))
    else:
        conn.execute(ddl)


def _0029_handover_date_required(conn: Any) -> None:
    """Every EV assignment gets a handover date, and can never lose one again.

    ``handover_date`` was nullable and the schema described NULL as "rent the
    full cycle (legacy riders)". That held while the only NULL rows came from
    the go-live import. Once the EV screens and the payout importer could write
    NULL too, an assignment with no date had nothing to compare a cycle
    against, so rent billed it for **every** cycle, in full, at its own EV's
    rate — including cycles that closed before the vehicle was handed over. It
    reached riders' payslips: one paid rent for two EVs in a week he had one,
    another paid a rate belonging to a vehicle he had not yet been given.

    The backfill, in order of what it can actually know:

    1. ``created_at`` — we cannot have handed over a vehicle before we wrote
       the row saying we had, so its date is the honest floor.
    2. the earliest cycle the office has ever run, for rows old enough to
       predate ``created_at`` defaults.
    3. ``2020-01-01`` — before the business existed, so it charges from the
       first cycle that sees the rider and never reaches backwards.

    None of these invent a *later* date than the truth, which matters: a date
    that is too early can only under-charge a rider, and under-charging is
    recoverable in a way that a wrong deduction from somebody's pay is not.

    The NOT NULL itself is applied on PostgreSQL only. Production is Postgres,
    where it is one statement; SQLite would need a twelve-step rebuild of a
    table three others reference by foreign key, which is a bigger risk than
    the bug it closes. Fresh databases of both kinds get the constraint from
    schema.py, so the tests run against it.
    """
    fallback = conn.execute("SELECT MIN(cycle_start) AS d FROM company_cycles").fetchone()
    floor = (fallback["d"] if fallback else None) or "2020-01-01"
    conn.execute(
        "UPDATE ev_assignments SET handover_date = "
        "  COALESCE(substr(created_at, 1, 10), ?) "
        "WHERE handover_date IS NULL",
        (floor,),
    )
    if DB_URL:
        conn.execute("ALTER TABLE ev_assignments ALTER COLUMN handover_date SET NOT NULL")


def _0030_adhoc_runs(conn: Any) -> None:
    """The ledger of ad-hoc payments — surge riders paid outside any cycle.

    Kept apart from ``company_cycles`` on purpose. An ad-hoc run must not make
    a week read as paid, or the next normal cycle would find its slot taken and
    the rent for those days would never be billed. The unique index on
    ``(company, file_digest)`` is what stops the same surge payment going out
    twice: there is no cycle window to guard it, so the file's own content —
    who is paid, and how much — is the identity.
    """
    ddl = (
        "CREATE TABLE IF NOT EXISTS adhoc_runs ("
        "  id          INTEGER PRIMARY KEY AUTOINCREMENT,"
        "  company     TEXT NOT NULL,"
        "  ran_on      TEXT NOT NULL,"
        "  label       TEXT,"
        "  file_digest TEXT NOT NULL,"
        "  riders      INTEGER NOT NULL DEFAULT 0,"
        "  total_paid  INTEGER NOT NULL DEFAULT 0,"
        "  created_by  TEXT,"
        "  created_at  TEXT DEFAULT (datetime('now'))"
        ")"
    )
    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(ddl))
    else:
        conn.execute(ddl)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_adhoc_digest ON adhoc_runs (company, file_digest)"
    )


def _0031_rider_account_name(conn: Any) -> None:
    """Whose name the bank account is in.

    Riders are often paid into an account belonging to a wife, a father, a
    brother — the money still has to reach them, and a payout file that
    disagrees with the beneficiary name gets bounced by the bank. Until now
    the only name on a ``rider_master`` row was the rider's own.

    Left NULL, it means "the same as the rider", and every read falls back to
    ``name``. That way correcting a rider's spelling corrects the holder name
    with it, and a stored value always means somebody deliberately said the
    account is in a different name. Nothing is backfilled: a copy of every
    rider's own name would destroy exactly that distinction.

    ``recruiter_profiles.account_name`` (migration 0025) is the same field for
    staff; this is the rider side of it.
    """
    add_column(conn, "rider_master", "account_name", "TEXT")


def _0032_head_recruiter(conn: Any) -> None:
    """Head recruiter for a zone.

    A flag rather than a rung on the ladder. ``ROLE_RANK`` is load-bearing in
    the money fence (``no_recruiter``) and in who-may-act-on-whom
    (``require_admin_over``); inserting a role between recruiter and admin
    would mean re-reasoning every guard in the codebase, and a mistake there
    is a privilege bug rather than a cosmetic one. As a flag it composes: a
    head is still a ``recruiter`` everywhere, still cannot see money, and the
    zone fence they already obey becomes the scope of what they supervise.

    Nobody is a head until somebody says so, hence DEFAULT 0.
    """
    add_column(conn, "users", "is_head", "INTEGER NOT NULL DEFAULT 0")


MIGRATIONS: list[tuple[str, Callable[[Any], None]]] = [
    ("0001_baseline", _baseline),
    ("0002_reset_token_attempts", _0002_reset_token_attempts),
    ("0003_companies_shared_rider_ids", _0003_companies_shared_rider_ids),
    ("0004_offset_credit_vs_arrears", _0004_offset_credit_vs_arrears),
    ("0005_deposit_for_closed_evs", _0005_deposit_for_closed_evs),
    ("0006_collapse_bluedart", _0006_collapse_bluedart),
    ("0007_cod_hub_and_spencers_layout", _0007_cod_hub_and_spencers_layout),
    ("0008_cod_hub_code", _0008_cod_hub_code),
    ("0009_suspected_return_dismissals", _0009_suspected_return_dismissals),
    ("0010_users_phone", _0010_users_phone),
    ("0011_collapse_raft_warrior_models", _0011_collapse_raft_warrior_models),
    ("0012_person_identity_numbers", _0012_person_identity_numbers),
    ("0013_company_payment_model", _0013_company_payment_model),
    ("0014_seed_direct_and_per_order_companies", _0014_seed_direct_and_per_order_companies),
    ("0015_salary_model", _0015_salary_model),
    (
        "0016_pidge_delhivery_retire_bluedart_dealshare",
        _0016_pidge_delhivery_retire_bluedart_dealshare,
    ),
    ("0017_refresh_tokens", _0017_refresh_tokens),
    ("0018_recruiter_app_fields", _0018_recruiter_app_fields),
    ("0019_recruiter_locations", _0019_recruiter_locations),
    ("0020_ev_closeouts", _0020_ev_closeouts),
    ("0021_referrals", _0021_referrals),
    ("0022_ev_requests", _0022_ev_requests),
    ("0023_app_crashes", _0023_app_crashes),
    ("0024_rename_companies", _0024_rename_companies),
    ("0025_recruiter_profiles", _0025_recruiter_profiles),
    ("0026_ev_assignment_actor", _0026_ev_assignment_actor),
    ("0027_recruiter_shifts", _0027_recruiter_shifts),
    ("0028_ev_closeout_reports", _0028_ev_closeout_reports),
    ("0029_handover_date_required", _0029_handover_date_required),
    ("0030_adhoc_runs", _0030_adhoc_runs),
    ("0031_rider_account_name", _0031_rider_account_name),
    ("0032_head_recruiter", _0032_head_recruiter),
]

_TRACKING_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_migrations ("
    "  name       TEXT PRIMARY KEY,"
    "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
    ")"
)


def _ensure_tracking_table(conn: Any) -> None:
    if DB_URL:
        from payout.db.connection import translate_ddl

        conn.executescript(translate_ddl(_TRACKING_DDL))
    else:
        conn.execute(_TRACKING_DDL)


def _applied(conn: Any) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}


def _record(conn: Any, name: str) -> None:
    conn.execute("INSERT OR IGNORE INTO schema_migrations (name) VALUES (?)", (name,))


def run_migrations(
    conn: Any,
    *,
    fresh_database: bool,
    legacy_hook: Callable[[Any], None] | None = None,
) -> list[str]:
    """Bring ``conn`` to the latest schema. Returns the names that were applied.

    ``fresh_database`` must be computed *before* ``apply_schema`` ran (see
    ``initialize_database``). ``legacy_hook`` is the old SQLite-only migrator,
    run once on databases that predate this runner.
    """
    had_tracking = table_exists(conn, "schema_migrations")
    _ensure_tracking_table(conn)
    applied = _applied(conn)
    ran: list[str] = []

    if fresh_database:
        # SCHEMA already has every column; just stamp the ledger.
        for name, _fn in MIGRATIONS:
            if name not in applied:
                _record(conn, name)
        return ran

    if not had_tracking and MIGRATIONS[0][0] not in applied:
        # Pre-runner database: reach the baseline the old way, then stamp it.
        if legacy_hook is not None:
            legacy_hook(conn)
        _record(conn, MIGRATIONS[0][0])
        applied.add(MIGRATIONS[0][0])

    for name, fn in MIGRATIONS:
        if name in applied:
            continue
        fn(conn)
        _record(conn, name)
        ran.append(name)
    return ran


__all__ = ["MIGRATIONS", "add_column", "has_column", "run_migrations", "table_exists"]
