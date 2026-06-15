"""Shared pytest fixtures. Tests run against a disposable SQLite DB in /tmp."""

import os

os.environ.setdefault("PAYOUT_DB", "/tmp/pytest_payout.db")

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from payout.db import get_connection, initialize_database  # noqa: E402


@pytest.fixture
def db():
    """A freshly initialised database connection, reset for each test."""
    path = os.environ["PAYOUT_DB"]
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(path + suffix).unlink()
        except FileNotFoundError:
            pass
    initialize_database()
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()
