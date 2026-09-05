"""Seed reference data: EV rate-card models and company parser configs.

All inserts use ``INSERT OR IGNORE`` so seeding is idempotent and never
overwrites edits made later through the admin tools.
"""

from __future__ import annotations

import sqlite3

# (provider, model_name, weekly_rate). Daily rate is derived as weekly / 7.
EV_MODELS: list[tuple[str, str, float]] = [
    ("Raft", "Regular", 125000),  # paise
    ("Raft", "Blue", 129500),  # paise
    ("Blive", "Standard", 126000),  # paise
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
        # Provisional (2026-09): no Nykaa sample file yet, so the layout is a
        # clone of Blitz's. Adjust the columns with `payout-admin update-company`
        # once a real file arrives. Nykaa pays Blitz riders under their BLITZ rider ids — the
        # engine links an unknown Nykaa id to the same id at Blitz automatically
        # (companies.rider_ids_shared_with).
        "company_name": "Nykaa",
        "parser_type": "nykaa",
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
        "rider_ids_shared_with": "Blitz",
    },
    {
        "company_name": "Myntra",
        "parser_type": "myntra",
        "payout_sheet": "0",
        "rider_id_column": "Worker Code",
        "payout_column": "Final Payout",
        "orders_column": "Total Order Completed",
        "has_hold_sheet": 1,
        "hold_style": "column",  # inline COD-Pending column
        "hold_sheet": None,
        "hold_key_column": None,
        "hold_amount_column": "COD-Pending",
        "hold_status_column": None,
        "is_active": 1,
    },
    {
        "company_name": "Spencer's",
        "parser_type": "spencers",
        # Sheets are now named WEEK1, WEEK2, … so we just take the first sheet
        # (the parser also finds the payout sheet by its columns).
        "payout_sheet": None,
        # Two layouts in the wild: the classic "Rider id / Total Payable Amount /
        # Delivered Orders" sheet, and the 2026-08 export keyed on rider_phone
        # (the rider id IS the phone number) with "Total Payable" and
        # "total_orders_delivered". "|" separates the accepted headers.
        "rider_id_column": "Rider id|rider_phone",
        "payout_column": "Total Payable Amount|Total Payable",
        "orders_column": "Delivered Orders|total_orders_delivered",
        "has_hold_sheet": 1,
        "hold_style": "sheet",
        "hold_sheet": "COD",  # found by content too ("COD HOLD" in the new export)
        "hold_key_column": "WORKER CODE",
        "hold_amount_column": "AMOUNT",
        "hold_status_column": None,
        "is_active": 1,
        "cadence": "slots",
    },
    # ── Companies without a payout file (2026-09) ──────────────────────────
    # Zomato and Flipkart pay riders themselves: roster only, nothing to
    # process. Shadowfax sends no file either — the office reads each rider's
    # order count off the Shadowfax dashboard and we pay ₹15 an order.
    {
        "company_name": "Zomato",
        "parser_type": "none",
        "payout_sheet": None,
        "rider_id_column": "rider_id",
        "payout_column": "payout",
        "orders_column": "orders",
        "has_hold_sheet": 0,
        "hold_style": None,
        "hold_sheet": None,
        "hold_key_column": None,
        "hold_amount_column": None,
        "hold_status_column": None,
        "is_active": 1,
        "payment_model": "direct",
        "notes": "Pays riders directly. Roster only — no payout file.",
    },
    {
        "company_name": "Shadowfax",
        "parser_type": "orders",
        "payout_sheet": None,
        "rider_id_column": "rider_id",
        "payout_column": "payout",
        "orders_column": "orders",
        "has_hold_sheet": 0,
        "hold_style": None,
        "hold_sheet": None,
        "hold_key_column": None,
        "hold_amount_column": None,
        "hold_status_column": None,
        "is_active": 1,
        "payment_model": "per_order",
        "per_order_rate": 1500,
        "notes": "No payout file. Order counts come from the Shadowfax dashboard; "
        "₹15 per order paid by us.",
    },
    {
        "company_name": "Flipkart",
        "parser_type": "none",
        "payout_sheet": None,
        "rider_id_column": "rider_id",
        "payout_column": "payout",
        "orders_column": "orders",
        "has_hold_sheet": 0,
        "hold_style": None,
        "hold_sheet": None,
        "hold_key_column": None,
        "hold_amount_column": None,
        "hold_status_column": None,
        "is_active": 1,
        "payment_model": "direct",
        "notes": "Salary based — details not settled yet; assumed to pay riders directly.",
    },
]

_COMPANY_DEFAULTS = {
    "rider_ids_shared_with": None,
    "payment_model": "payout_file",
    "cadence": "weekly",
    "per_order_rate": None,
    "notes": None,
}


def seed_ev_models(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO ev_models (provider, model_name, weekly_rate) VALUES (?, ?, ?)",
        EV_MODELS,
    )


def seed_companies(conn: sqlite3.Connection) -> None:
    conn.executemany(
        """
        INSERT OR IGNORE INTO companies
            (company_name, parser_type, payout_sheet, rider_id_column,
             payout_column, orders_column, has_hold_sheet, hold_style,
             hold_sheet, hold_key_column, hold_amount_column,
             hold_status_column, is_active, rider_ids_shared_with,
             payment_model, cadence, per_order_rate, notes)
        VALUES
            (:company_name, :parser_type, :payout_sheet, :rider_id_column,
             :payout_column, :orders_column, :has_hold_sheet, :hold_style,
             :hold_sheet, :hold_key_column, :hold_amount_column,
             :hold_status_column, :is_active, :rider_ids_shared_with,
             :payment_model, :cadence, :per_order_rate, :notes)
        """,
        [{**_COMPANY_DEFAULTS, **c} for c in COMPANIES],
    )


def seed_all(conn: sqlite3.Connection) -> None:
    """Seed every reference table."""
    seed_ev_models(conn)
    seed_companies(conn)
