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
        # be an identifier on Postgres, not a string.
        conn.execute(
            f"UPDATE companies SET {col}=? WHERE company_name=? AND {col}=?",
            (new, "Spencer's", old),
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
