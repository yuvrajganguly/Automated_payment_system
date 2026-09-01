"""The versioned migration runner (payout.db.migrations).

Three databases must all end up identical:
1. a fresh one (SCHEMA already has every column → migrations are only stamped),
2. one created before the runner existed (no schema_migrations table, old
   column set → legacy hook + every migration runs),
3. one already migrated (nothing to do).
"""
from __future__ import annotations

from payout.db import get_connection, initialize_database
from payout.db.migrations import MIGRATIONS, has_column, run_migrations, table_exists
from payout.db.schema import SCHEMA, apply_schema
from tests.conftest import reset_database

# Columns introduced by the migrations after the baseline (table, column).
_NEW_COLUMNS = [
    ("password_reset_tokens", "attempts"),
    ("companies", "rider_ids_shared_with"),
]


def _stamped(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}


def test_fresh_database_is_stamped_not_migrated(db):
    assert _stamped(db) == {name for name, _ in MIGRATIONS}
    for table, col in _NEW_COLUMNS:
        assert has_column(db, table, col), (table, col)


def test_rerun_is_a_no_op(db):
    assert initialize_database() == []


def test_pre_runner_database_gets_every_migration():
    """Build a database that predates the runner: no schema_migrations table and
    none of the post-baseline columns. initialize_database() must add them all
    and record every migration, on either backend."""
    reset_database()
    old_schema = SCHEMA
    # Strip the newer columns out of the DDL so the tables look like the past.
    old_schema = old_schema.replace(
        "    attempts   INTEGER NOT NULL DEFAULT 0, -- wrong guesses; locked after MAX_OTP_ATTEMPTS\n",
        "",
    )
    old_schema = old_schema.replace(
        "    is_active          INTEGER NOT NULL DEFAULT 1,\n"
        "    -- Name of another company whose rider IDs this company reuses (Nykaa pays\n"
        "    -- Blitz riders under their Blitz IDs). An unknown rider_id in this\n"
        "    -- company's file that exists under that company is linked automatically.\n"
        "    rider_ids_shared_with TEXT\n",
        "    is_active          INTEGER NOT NULL DEFAULT 1\n",
    )
    assert "attempts" not in old_schema and "rider_ids_shared_with" not in old_schema

    import payout.db.schema as schema_mod

    with get_connection() as conn:
        original = schema_mod.SCHEMA
        schema_mod.SCHEMA = old_schema
        try:
            apply_schema(conn)
        finally:
            schema_mod.SCHEMA = original
        conn.commit()
        assert not table_exists(conn, "schema_migrations")
        for table, col in _NEW_COLUMNS:
            assert not has_column(conn, table, col), (table, col)

    applied = initialize_database()
    assert applied == [name for name, _ in MIGRATIONS[1:]]

    with get_connection() as conn:
        assert _stamped(conn) == {name for name, _ in MIGRATIONS}
        for table, col in _NEW_COLUMNS:
            assert has_column(conn, table, col), (table, col)
        # idempotent: the columns exist, the steps must not fail if re-run
        assert run_migrations(conn, fresh_database=False) == []
