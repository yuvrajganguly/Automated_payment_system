"""Seed reference data: EV rate-card models and company parser configs.

All inserts use ``INSERT OR IGNORE`` so seeding is idempotent and never
overwrites edits made later through the admin tools.
"""

from __future__ import annotations

import sqlite3

# (provider, model_name, weekly_rate). Daily rate is derived as weekly / 7.
EV_MODELS: list[tuple[str, str, float]] = [
    ("Raft", "Regular", 1250.0),
    ("Raft", "Blue", 1295.0),
    ("Blive", "Standard", 1260.0),
]

# Company parser configs. See companies table in schema.py for column meanings.
COMPANIES: list[dict] = [
    {
        "company_name": "Dealshare",
        "parser_type": "dealshare",
        "payout_sheet": "pattern:Computation",  # sheet named "W## - Computation"
        "rider_id_column": "rider_id",
        "payout_column": "Final weekly payout",
        "orders_column": "total orders",
        "has_hold_sheet": 0,
        "hold_style": None,
        "hold_sheet": None,
        "hold_key_column": None,
        "hold_amount_column": None,
        "hold_status_column": None,
        "is_active": 1,
    },
    {
        "company_name": "Blitz",
        "parser_type": "blitz",
        "payout_sheet": "0",
        "rider_id_column": "rider_id",
        "payout_column": "net_pay",
        "orders_column": "total_del",
        "has_hold_sheet": 0,
        "hold_style": None,
        "hold_sheet": None,
        "hold_key_column": None,
        "hold_amount_column": None,
        "hold_status_column": None,
        "is_active": 1,
    },
    {
        "company_name": "Myntra",
        "parser_type": "myntra",
        "payout_sheet": "0",
        "rider_id_column": "Worker Code",
        "payout_column": "Final Payout",
        "orders_column": "Total Order Completed",
        "has_hold_sheet": 1,
        "hold_style": "column",          # inline COD-Pending column
        "hold_sheet": None,
        "hold_key_column": None,
        "hold_amount_column": "COD-Pending",
        "hold_status_column": None,
        "is_active": 1,
    },
    {
        "company_name": "Spencer's",
        "parser_type": "spencers",
        # Sheets are now named WEEK1, WEEK2, … so we just take the first sheet.
        "payout_sheet": None,
        "rider_id_column": "Rider id",
        "payout_column": "Total Payable Amount",
        "orders_column": "Delivered Orders",
        "has_hold_sheet": 1,
        "hold_style": "sheet",
        "hold_sheet": "COD",
        "hold_key_column": "WORKER CODE",
        "hold_amount_column": "AMOUNT",
        "hold_status_column": None,
        "is_active": 1,
    },
]


def seed_ev_models(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO ev_models (provider, model_name, weekly_rate) "
        "VALUES (?, ?, ?)",
        EV_MODELS,
    )


def seed_companies(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """
        INSERT OR IGNORE INTO companies
            (company_name, parser_type, payout_sheet, rider_id_column,
             payout_column, orders_column, has_hold_sheet, hold_style,
             hold_sheet, hold_key_column, hold_amount_column,
             hold_status_column, is_active)
        VALUES
            (:company_name, :parser_type, :payout_sheet, :rider_id_column,
             :payout_column, :orders_column, :has_hold_sheet, :hold_style,
             :hold_sheet, :hold_key_column, :hold_amount_column,
             :hold_status_column, :is_active)
        """,
        COMPANIES,
    )


def seed_all(conn: sqlite3.Connection) -> None:
    """Seed every reference table."""
    seed_ev_models(conn)
    seed_companies(conn)
