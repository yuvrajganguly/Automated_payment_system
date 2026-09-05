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
    ("cod_holds", "hub"),
    ("cod_holds", "worker_name"),
    ("cod_holds", "hub_code"),
    ("users", "phone"),
    ("companies", "payment_model"),
    ("companies", "per_order_rate"),
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
        "    attempts   INTEGER NOT NULL DEFAULT 0, -- wrong guesses; locked after MAX_OTP_ATTEMPTS\n",  # noqa: E501
        "",
    )
    old_schema = old_schema.replace(
        "    is_active          INTEGER NOT NULL DEFAULT 1,\n"
        "    -- Name of another company whose rider IDs this company reuses (Nykaa pays\n"
        "    -- Blitz riders under their Blitz IDs). An unknown rider_id in this\n"
        "    -- company's file that exists under that company is linked automatically.\n"
        "    rider_ids_shared_with TEXT,\n"
        "    -- How the company pays (2026-09):\n"
        "    --   payout_file : they send a payout file; we parse it, deduct rent, release\n"
        "    --   per_order   : no file — the office counts orders and pays per_order_rate\n"
        "    --   direct      : they pay riders themselves; we only keep the roster\n"
        "    payment_model      TEXT NOT NULL DEFAULT 'payout_file',\n"
        "    -- weekly | monthly | slots (Spencer's 1-7 / 8-14 / 15-21 / 22-end)\n"
        "    cadence            TEXT NOT NULL DEFAULT 'weekly',\n"
        "    per_order_rate     INTEGER,            -- paise per order (per_order only)\n"
        "    notes              TEXT\n",
        "    is_active          INTEGER NOT NULL DEFAULT 1\n",
    )
    old_schema = old_schema.replace(
        "    -- Hub/store code and worker name exactly as the company's COD sheet\n"
        "    -- states them. A COD rider need not be in the payout (or on the roster),\n"
        "    -- so the file is the only source for these.\n"
        "    hub          TEXT,           -- hub NAME (code resolved via hub_codes when known)\n"
        "    hub_code     TEXT,           -- the code exactly as the COD sheet stated it\n"
        "    worker_name  TEXT,\n",
        "",
    )
    old_schema = old_schema.replace(
        "    phone         TEXT,                           -- E.164 (+91…); second login id\n",
        "",
    )
    assert "phone         TEXT" not in old_schema
    assert "attempts" not in old_schema and "rider_ids_shared_with" not in old_schema
    assert "payment_model" not in old_schema
    assert "worker_name" not in old_schema and "hub_code     TEXT" not in old_schema

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


def test_0007_upgrades_stock_spencers_config_only():
    """An existing DB whose Spencer's row still carries the pre-2026-08 headers
    gets the '|'-alternatives; a row the operator customised is left alone."""
    from payout.db.migrations import _0007_cod_hub_and_spencers_layout

    reset_database()
    initialize_database()
    with get_connection() as conn:
        conn.execute(
            "UPDATE companies SET rider_id_column='Rider id', "
            "payout_column='Total Payable Amount', orders_column='Delivered Orders' "
            "WHERE company_name=?",
            ("Spencer's",),
        )
        conn.execute(
            "INSERT INTO companies (company_name, parser_type, rider_id_column, payout_column, "
            "orders_column) VALUES ('Custom', 'generic', 'Rider id', 'My Pay', 'Delivered Orders')"
        )
        _0007_cod_hub_and_spencers_layout(conn)
        sp = conn.execute(
            "SELECT rider_id_column, payout_column, orders_column FROM companies "
            "WHERE company_name=?",
            ("Spencer's",),
        ).fetchone()
        assert tuple(sp) == (
            "Rider id|rider_phone",
            "Total Payable Amount|Total Payable",
            "Delivered Orders|total_orders_delivered",
        )
        other = conn.execute(
            "SELECT rider_id_column, payout_column FROM companies WHERE company_name='Custom'"
        ).fetchone()
        assert tuple(other) == ("Rider id", "My Pay")
        conn.rollback()


def test_0011_collapses_raft_warrior_into_regular_only_at_equal_rate(db):
    from payout.db.migrations import _0011_collapse_raft_warrior_models

    reg = db.execute(
        "SELECT model_id, weekly_rate FROM ev_models WHERE provider='Raft' AND model_name='Regular'"
    ).fetchone()
    db.execute(
        "INSERT INTO ev_models (provider, model_name, weekly_rate) VALUES ('Raft','WARRIOR',?)",
        (reg["weekly_rate"],),
    )
    db.execute(
        "INSERT INTO ev_models (provider, model_name, weekly_rate) VALUES ('Raft','WARRIOR 2.0',?)",
        (reg["weekly_rate"],),
    )
    db.execute(
        "INSERT INTO ev_models (provider, model_name, weekly_rate) VALUES ('Raft','WARRIOR X',?)",
        (reg["weekly_rate"] + 5000,),
    )
    ids = {
        r["model_name"]: r["model_id"]
        for r in db.execute("SELECT model_id, model_name FROM ev_models WHERE provider='Raft'")
    }
    for ev, m in (("W1", "WARRIOR"), ("W2", "WARRIOR 2.0"), ("WX", "WARRIOR X")):
        db.execute(
            "INSERT INTO ev_units (ev_id, model_id, status) VALUES (?,?,'spare')", (ev, ids[m])
        )
    db.commit()
    _0011_collapse_raft_warrior_models(db)
    db.commit()
    left = {
        r["model_name"]
        for r in db.execute("SELECT model_name FROM ev_models WHERE provider='Raft'")
    }
    assert "WARRIOR" not in left and "WARRIOR 2.0" not in left and "WARRIOR X" in left
    units = {
        r["ev_id"]: r["model_id"]
        for r in db.execute("SELECT ev_id, model_id FROM ev_units WHERE ev_id IN ('W1','W2','WX')")
    }
    assert units["W1"] == reg["model_id"] and units["W2"] == reg["model_id"]
    assert units["WX"] == ids["WARRIOR X"]  # different rate: left for the operator


def test_0013_0014_payment_model_and_new_companies(db):
    """Fresh DB: seed carries the three file-less companies with their model;
    Spencer's is the slots company. Re-running 0014 never duplicates."""
    rows = {
        r["company_name"]: dict(r)
        for r in db.execute(
            "SELECT company_name, payment_model, cadence, per_order_rate, parser_type "
            "FROM companies"
        )
    }
    assert rows["Zomato"]["payment_model"] == "direct"
    assert rows["Flipkart"]["payment_model"] == "direct"
    assert rows["Shadowfax"]["payment_model"] == "per_order"
    assert rows["Shadowfax"]["per_order_rate"] == 1500
    assert rows["Spencer's"]["cadence"] == "slots"
    assert rows["Blitz"]["payment_model"] == "payout_file"
    from payout.db.migrations import _0014_seed_direct_and_per_order_companies

    _0014_seed_direct_and_per_order_companies(db)
    assert (
        db.execute("SELECT COUNT(*) FROM companies WHERE company_name='Zomato'").fetchone()[0] == 1
    )


def test_cadence_next_cycle():
    from datetime import date

    from payout.domain.cycles import next_cycle_for

    assert next_cycle_for("Anything", date(2026, 8, 31), "monthly") == (
        date(2026, 9, 1),
        date(2026, 9, 30),
    )
    assert next_cycle_for("X", date(2026, 12, 31), "monthly") == (
        date(2027, 1, 1),
        date(2027, 1, 31),
    )
    assert next_cycle_for("X", date(2026, 9, 7), "slots") == (date(2026, 9, 8), date(2026, 9, 14))
    assert next_cycle_for("X", date(2026, 9, 6), "weekly") == (date(2026, 9, 7), date(2026, 9, 13))
    # No cadence given: Spencer's is still the slots company.
    assert next_cycle_for("Spencer's", date(2026, 9, 14)) == (date(2026, 9, 15), date(2026, 9, 21))
