"""Shared pytest fixtures.

Runs against a disposable SQLite file in a per-session temp directory by
default. If ``PAYOUT_DB_URL`` is set (a Postgres URL) the same tests run against
Postgres — the public schema is dropped and recreated for each test so every
case starts clean.

Safety: the suite DELETES the database it points at. So we never inherit a
developer's ``PAYOUT_DB`` from the shell (it is overridden with a temp path), and
a Postgres URL is only accepted when the database name ends in ``_test``.
"""

import os
import tempfile
from urllib.parse import urlparse

# --- environment must be pinned BEFORE payout.config is imported -------------
_TMP_DIR = tempfile.mkdtemp(prefix="payout-pytest-")
os.environ["PAYOUT_DB"] = os.path.join(_TMP_DIR, "payout.db")
# Tests never carry a real secret; opt into the dev secret explicitly.
os.environ.setdefault("PAYOUT_JWT_SECRET", "pytest-only-secret-not-for-production!!")
os.environ.setdefault("PAYOUT_ALLOW_DEV_SECRET", "1")
os.environ.setdefault("PAYOUT_SEED_DEMO", "0")

_pg_url = os.environ.get("PAYOUT_DB_URL")
if _pg_url:
    _db_name = (urlparse(_pg_url).path or "").lstrip("/")
    if not _db_name.endswith("_test"):
        raise SystemExit(
            f"Refusing to run tests against PAYOUT_DB_URL database {_db_name!r}: the suite "
            "drops the whole schema. Point it at a database whose name ends in '_test'."
        )

from pathlib import Path  # noqa: E402

import pytest  # noqa: E402

from payout.config import DB_URL  # noqa: E402
from payout.db import get_connection, initialize_database  # noqa: E402


def reset_database() -> None:
    """Destroy the test database so the next ``initialize_database`` is fresh."""
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
    reset_database()
    initialize_database()
    conn = get_connection()
    try:
        yield conn
    finally:
        conn.close()


# ── row factories ────────────────────────────────────────────────────────────
# The same five INSERTs were copy-pasted across a dozen test files. Use these.


def make_person(db, name="Rider", *, balance=None, arrears=None) -> int:
    pid = db.execute(
        "INSERT INTO person_registry (display_name) VALUES (?)", (name,)
    ).lastrowid
    if balance is not None:
        db.execute(
            "INSERT INTO balances (person_id, current_balance) VALUES (?, ?)", (pid, balance)
        )
    if arrears is not None:
        db.execute(
            "INSERT INTO ev_arrears (person_id, total_missed, total_recovered, outstanding) "
            "VALUES (?, ?, 0, ?)",
            (pid, arrears, arrears),
        )
    return pid


def make_rider(db, person_id: int, rider_id: str, company: str, name="Rider") -> None:
    db.execute(
        "INSERT INTO rider_master (rider_id, company, person_id, name, is_active) "
        "VALUES (?, ?, ?, ?, 1)",
        (rider_id, company, person_id, name),
    )


def model_id(db, provider="Blive", model="Standard") -> int:
    return db.execute(
        "SELECT model_id FROM ev_models WHERE provider=? AND model_name=?", (provider, model)
    ).fetchone()["model_id"]


def make_ev(db, ev_id: str, *, provider="Blive", model="Standard", status="spare") -> str:
    db.execute(
        "INSERT INTO ev_units (ev_id, model_id, status) VALUES (?, ?, ?)",
        (ev_id, model_id(db, provider, model), status),
    )
    return ev_id


def assign(
    db, person_id: int, ev_id: str, *, handover=None, returned=None, charged_through=None
) -> int:
    aid = db.execute(
        "INSERT INTO ev_assignments (person_id, ev_id, handover_date, returned_date, "
        "rent_charged_through) VALUES (?, ?, ?, ?, ?)",
        (person_id, ev_id, handover, returned, charged_through),
    ).lastrowid
    db.execute("UPDATE ev_units SET status=? WHERE ev_id=?",
               ("returned" if returned else "in_use", ev_id))
    return aid
