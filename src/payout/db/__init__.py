"""Data-access layer: connection handling, schema, and seed data."""

from __future__ import annotations

from payout.db.connection import get_connection
from payout.db.schema import apply_schema
from payout.db.seed import seed_all


def _migrate(conn) -> None:
    """Apply small forward-only schema migrations to existing DBs."""
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
    # balances: cross-company rent slot (v0.4)
    bal_cols = {r[1] for r in conn.execute("PRAGMA table_info(balances)")}
    if "pending_xc_rent" not in bal_cols:
        conn.execute("ALTER TABLE balances ADD COLUMN pending_xc_rent REAL NOT NULL DEFAULT 0")
    if "xc_origin_company" not in bal_cols:
        conn.execute("ALTER TABLE balances ADD COLUMN xc_origin_company TEXT")
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


def initialize_database() -> None:
    """Create the schema (if missing) and seed reference data.

    Safe to run repeatedly — schema uses ``CREATE TABLE IF NOT EXISTS`` and
    seeds use ``INSERT OR IGNORE``. Also applies forward-only migrations
    against pre-existing tables.
    """
    with get_connection() as conn:
        apply_schema(conn)
        _migrate(conn)
        seed_all(conn)
        conn.commit()


__all__ = ["get_connection", "apply_schema", "seed_all", "initialize_database"]
