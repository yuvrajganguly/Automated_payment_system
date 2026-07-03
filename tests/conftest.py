"""Shared pytest fixtures.

Runs against a disposable SQLite DB in /tmp by default. If ``PAYOUT_DB_URL`` is
set (a Postgres URL), the same tests run against Postgres — the public schema is
dropped and recreated for each test so every case starts clean.
"""

import os

os.environ.setdefault("PAYOUT_DB", "/tmp/pytest_payout.db")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from payout.config import DB_URL  # noqa: E402
from payout.db import get_connection, initialize_database  # noqa: E402


def _reset() -> None:
    if DB_URL:
        import psycopg
        with psycopg.connect(DB_URL, autocommit=True) as c:
            c.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
    else:
        path = os.environ["PAYOUT_DB"]
        for suffix in ("", "-wal", "-shm"):
            try:
                Path(path + suffix).unlink()
            except FileNotFoundError:
                pass


@pytest.fixture
def db():
    """A freshly initialised database connection, reset for each test."""
    _reset()
    initialize_database()
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
