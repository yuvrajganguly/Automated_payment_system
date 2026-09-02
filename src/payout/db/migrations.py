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


MIGRATIONS: list[tuple[str, Callable[[Any], None]]] = [
    ("0001_baseline", _baseline),
    ("0002_reset_token_attempts", _0002_reset_token_attempts),
    ("0003_companies_shared_rider_ids", _0003_companies_shared_rider_ids),
    ("0004_offset_credit_vs_arrears", _0004_offset_credit_vs_arrears),
    ("0005_deposit_for_closed_evs", _0005_deposit_for_closed_evs),
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
