"""SQLite connection helper."""

from __future__ import annotations

import sqlite3

from payout.config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """Open a SQLite connection with sane defaults.

    - ``Row`` factory so columns are accessible by name.
    - Foreign keys enforced (off by default in SQLite).
    - WAL journal mode for better concurrent reads.
    """
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn
