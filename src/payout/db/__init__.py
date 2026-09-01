"""Data-access layer: connection handling, schema, and seed data."""

from __future__ import annotations

from payout.db.connection import get_connection
from payout.db.migrations import run_migrations, table_exists
from payout.db.schema import apply_schema
from payout.db.seed import seed_all


def _legacy_sqlite_migrate(conn) -> None:
    """The pre-``schema_migrations`` migrator, kept only to bring an old SQLite
    file up to the ``0001_baseline`` state exactly once. New schema changes go
    in ``payout.db.migrations.MIGRATIONS`` — never here.

    Uses SQLite-only introspection (PRAGMA table_info) and table rebuilds; a
    Postgres database can never predate the baseline, so it is a no-op there.
    """
    from payout.config import DB_URL

    if DB_URL:
        return
    # ev_arrears: add COD columns (v0.1 → v0.2)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ev_arrears)")}
    for col in ("cod_missed", "cod_recovered", "cod_outstanding"):
        if col not in cols:
            conn.execute(f"ALTER TABLE ev_arrears ADD COLUMN {col} REAL NOT NULL DEFAULT 0")
    # cod_holds: add clearance audit (v0.3)
    cod_cols = {r[1] for r in conn.execute("PRAGMA table_info(cod_holds)")}
    for col in ("cleared_at", "cleared_by"):
        if col not in cod_cols:
            conn.execute(f"ALTER TABLE cod_holds ADD COLUMN {col} TEXT")
    # companies: orders_column for delivered/completed orders pass-through (v0.6)
    co_cols = {r[1] for r in conn.execute("PRAGMA table_info(companies)")}
    if "orders_column" not in co_cols:
        conn.execute("ALTER TABLE companies ADD COLUMN orders_column TEXT")
        # Backfill defaults for the four known companies so existing DBs pick up
        # the column without needing the Settings UI tour.
        _backfill = (
            ("Spencer's", "Delivered Orders"),
            ("Myntra", "Total Order Completed"),
            ("Dealshare", "total orders"),
            ("Blitz", "total_del"),
        )
        for name, col in _backfill:
            conn.execute(
                "UPDATE companies SET orders_column=? "
                "WHERE company_name=? AND (orders_column IS NULL OR orders_column='')",
                (col, name),
            )
    # Spencer's renamed the column "Delivered Order" -> "Delivered Orders".
    # Idempotent fix-up: pull existing wrong value forward without touching
    # anything an operator may have customized.
    conn.execute(
        "UPDATE companies SET orders_column='Delivered Orders' "
        "WHERE company_name=\"Spencer's\" AND orders_column='Delivered Order'"
    )
    # Default any missing rider vehicle to BIKE — the runtime display already
    # derives EV/BIKE from EV assignment status, but normalising the raw column
    # keeps reports/exports consistent.
    conn.execute("UPDATE rider_master SET vehicle='BIKE' WHERE vehicle IS NULL OR TRIM(vehicle)=''")
    # v0.8 — rename ev_daily_ledger.raft_cost → provider_cost (provider-agnostic).
    daily_cols = {r[1] for r in conn.execute("PRAGMA table_info(ev_daily_ledger)")}
    if "raft_cost" in daily_cols and "provider_cost" not in daily_cols:
        conn.execute("ALTER TABLE ev_daily_ledger RENAME COLUMN raft_cost TO provider_cost")
    # balances: cross-company rent slot (v0.4)
    bal_cols = {r[1] for r in conn.execute("PRAGMA table_info(balances)")}
    if "pending_xc_rent" not in bal_cols:
        conn.execute("ALTER TABLE balances ADD COLUMN pending_xc_rent REAL NOT NULL DEFAULT 0")
    if "xc_origin_company" not in bal_cols:
        conn.execute("ALTER TABLE balances ADD COLUMN xc_origin_company TEXT")
    # v0.7 — cycle_end of the cycle that produced pending_xc_rent, so the
    # engine can detect "a new cycle's RENT landed" and collapse the prior
    # bucket into general dues before charging fresh rent.
    if "xc_origin_cycle_end" not in bal_cols:
        conn.execute("ALTER TABLE balances ADD COLUMN xc_origin_cycle_end TEXT")
    # ev_maintenance.to_date: drop NOT NULL so open-ended windows can be NULL.
    # SQLite can't alter constraints, so rebuild the table when the current
    # definition still says NOT NULL.
    maint_cols = list(conn.execute("PRAGMA table_info(ev_maintenance)"))
    to_date_col = next((c for c in maint_cols if c[1] == "to_date"), None)
    if to_date_col is not None and to_date_col[3] == 1:  # cid,name,type,notnull,...
        conn.execute("""
            CREATE TABLE _ev_maintenance_new (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ev_id      TEXT NOT NULL REFERENCES ev_units(ev_id),
                from_date  TEXT NOT NULL,
                to_date    TEXT,
                reason     TEXT,
                created_at TEXT DEFAULT (datetime('now')),
                created_by TEXT
            )
        """)
        conn.execute(
            "INSERT INTO _ev_maintenance_new "
            "(id, ev_id, from_date, to_date, reason, created_at, created_by) "
            "SELECT id, ev_id, from_date, to_date, reason, created_at, created_by "
            "FROM ev_maintenance"
        )
        conn.execute("DROP TABLE ev_maintenance")
        conn.execute("ALTER TABLE _ev_maintenance_new RENAME TO ev_maintenance")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_maint_ev ON ev_maintenance (ev_id)")


def initialize_database() -> list[str]:
    """Create the schema (if missing), migrate, and seed reference data.

    Safe to run repeatedly — schema uses ``CREATE TABLE IF NOT EXISTS``, seeds
    use ``INSERT OR IGNORE``, and migrations are tracked in
    ``schema_migrations`` so each runs exactly once on both backends.
    Returns the names of the migrations applied in this call.
    """
    with get_connection() as conn:
        fresh = not table_exists(conn, "person_registry")
        apply_schema(conn)
        applied = run_migrations(conn, fresh_database=fresh, legacy_hook=_legacy_sqlite_migrate)
        seed_all(conn)
        conn.commit()
    return applied


__all__ = ["get_connection", "apply_schema", "seed_all", "initialize_database"]
