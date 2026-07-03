"""Central configuration — a single source of truth for paths and constants.

Everything that used to be hard-coded across modules (the database path, the
cycle length) lives here. Override the database location at runtime with the
``PAYOUT_DB`` environment variable, which keeps tests and deployments isolated
from your real data.
"""

from __future__ import annotations

import os
from pathlib import Path

# Resolve project paths relative to this file (src/payout/config.py).
PACKAGE_DIR: Path = Path(__file__).resolve().parent
SRC_DIR: Path = PACKAGE_DIR.parent
PROJECT_ROOT: Path = SRC_DIR.parent

# Database location. Override with `PAYOUT_DB=/some/path.db` for tests/deploys.
DB_PATH: Path = Path(os.environ.get("PAYOUT_DB", PROJECT_ROOT / "payout.db"))

# Optional PostgreSQL backend. When ``PAYOUT_DB_URL`` is set (e.g.
# ``postgresql://user:pass@host:5432/payout``), the app uses Postgres and the
# SQLite ``DB_PATH`` above is ignored. Unset => SQLite file (default).
DB_URL: str | None = os.environ.get("PAYOUT_DB_URL") or None

# A standard pay cycle is one week. Used to decide weekly-vs-daily EV rent.
STANDARD_CYCLE_DAYS: int = 7
