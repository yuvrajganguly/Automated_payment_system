"""Config-driven Excel parser.

A company's ``companies`` row fully describes how to read its file — which sheet
holds the payout, which columns carry the rider id and amount, and how holds are
expressed (a separate COD sheet, or an inline column). One parser therefore
handles every company, and onboarding a new one is just a config row. This is
the foundation the future UI "parser builder" will sit on.

Resilience built in:
  - columns matched by name (case-insensitive), so reordering / extra columns
    are harmless and minor renames are absorbed;
  - the payout and hold sheets are found by *content* (the columns they hold),
    so reordering or renaming sheets doesn't break parsing;
  - header rows are auto-detected, tolerating title/banner rows on top;
  - a genuine rename that can't be matched fails loudly with the columns it saw.
"""

from __future__ import annotations

import re
import sqlite3
from io import BytesIO

import pandas as pd

from payout.domain.models import CodHoldLine, ParseResult, RiderRecord
from payout.money import to_paise
from payout.parsers.base import match_column, read_table, select_sheet, to_float

# Every header a client has used for the rider id. Spencer's rider id IS the
# rider's phone number, and their 2026-08 layout calls the column rider_phone.
_RIDER_ALIASES = (
    "rider_id",
    "rider id",
    "riderid",
    "worker code",
    "worker_code",
    "rider_phone",
    "rider phone",
)
# Name column: Myntra files say "Name" or "Worker Name" depending on the
# export; both mean the rider's name.
_NAME_ALIASES = ("rider_name", "rider name", "name", "worker name", "worker_name")
# Hub / store column. Spencer's new layout carries the store as store_names
# (+ store_ids); older files used Store / Hub.
_HUB_ALIASES = (
    "store",
    "hub",
    "store/hub",
    "store_hub",
    "store name",
    "hub name",
    "store/hub name",
    "store_names",
    "store names",
    "store_name",
    "hub code",
    "hub_code",
    "store_ids",
    "store ids",
    "store_id",
    "store id",
)


_PHONEISH_RE = re.compile(r"^\+?\d[\d\s\-]*$")


def _normalise_rider_id(value) -> str:
    """Canonical rider id text.

    Excel hands numeric ids over as ``1234.0`` when the cell is a number; strip
    that, and surrounding whitespace. Ids that are phone numbers (Spencer's)
    arrive in every spelling a human types into a sheet — ``'+91 98765 43210``,
    ``098765-43210`` — and must match the plain ``9876543210`` on the payout
    sheet, so a purely numeric id is reduced to its digits and a leading
    country code (91) / trunk zero dropped from a 10-digit Indian number.
    Alphanumeric ids (``BD-12``) are left exactly as written.
    """
    if value is None:
        return ""
    text = str(value).strip().strip("'\"‘’“”").strip()
    if not text or text.lower() == "nan":
        return ""
    if text.endswith(".0") and text[:-2].isdigit():
        text = text[:-2]
    if _PHONEISH_RE.match(text):
        digits = re.sub(r"\D", "", text)
        if len(digits) == 12 and digits.startswith("91"):
            digits = digits[2:]
        elif len(digits) == 11 and digits.startswith("0"):
            digits = digits[1:]
        text = digits
    return text


def parse_with_config(file_bytes: bytes, config: sqlite3.Row) -> ParseResult:
    """Parse a payout file using a company's config row."""
    company = config["company_name"]
    warnings: list[str] = []
    xl = pd.ExcelFile(BytesIO(file_bytes))

    # ── Payout sheet (found by config, with content + header detection) ──────
    sheet, df = _resolve_payout_sheet(xl, config)
    rider_col = match_column(df.columns, config["rider_id_column"], *_RIDER_ALIASES)
    payout_col = match_column(df.columns, config["payout_column"])
    if not rider_col:
        raise ValueError(
            f"{company}: rider-id column '{config['rider_id_column']}' not found. "
            f"Sheet '{sheet}' columns: {list(df.columns)}"
        )
    if not payout_col:
        raise ValueError(
            f"{company}: payout column '{config['payout_column']}' not found. "
            f"Sheet '{sheet}' columns: {list(df.columns)}"
        )

    matched: dict[str, str] = {"rider_id": rider_col, "payout": payout_col}

    # Inline COD column (Myntra style).
    cod_col = None
    if config["has_hold_sheet"] and config["hold_style"] == "column":
        cod_col = match_column(df.columns, config["hold_amount_column"])
        if cod_col:
            matched["cod_pending"] = cod_col
        else:
            warnings.append(
                f"{company}: COD column '{config['hold_amount_column']}' not found; "
                "no inline holds applied"
            )

    # Optional orders/deliveries column (pass-through into the PAY sheet so
    # operators can sanity-check payout vs activity at a glance).
    orders_col_name = None
    try:  # noqa: SIM105
        orders_col_name = config["orders_column"]
    except (KeyError, IndexError):
        pass  # older DBs without the column — skip silently
    orders_col = None
    if orders_col_name:
        orders_col = match_column(df.columns, orders_col_name)
        if orders_col:
            matched["orders"] = orders_col
        else:
            warnings.append(
                f"{company}: orders column '{orders_col_name}' not found; leaving orders blank"
            )

    # Optional name and hub columns. We pull these from the file so the engine
    # can label unknown rider_ids with a real name + hub in the onboarding
    # modal (instead of just "id 8906377190 — who's that?").
    name_col = match_column(df.columns, *_NAME_ALIASES)
    hub_col = match_column(df.columns, *_HUB_ALIASES)
    if name_col:
        matched["name"] = name_col
    if hub_col:
        matched["hub"] = hub_col

    records: list[RiderRecord] = []
    seen: dict[str, int] = {}
    for _, row in df.iterrows():
        rider_id = _normalise_rider_id(row.get(rider_col, ""))
        if not rider_id:
            continue
        seen[rider_id] = seen.get(rider_id, 0) + 1
        raw_payout = row.get(payout_col)
        raw_text = "" if raw_payout is None else str(raw_payout).strip()
        payout = to_float(raw_payout)
        payout_invalid = None
        if payout is None and raw_text.lower() in ("", "nan", "none"):
            # Blank cell: the rider is in the file, so they are present; there
            # is just nothing to pay. (Dropping the row made the engine treat
            # them as ABSENT and charge the week to arrears.)
            payout = 0.0
            warnings.append(f"{company}: rider {rider_id} has a blank payout — treated as 0")
        elif payout is None:
            # Junk text ("N/A", a date, "abc"): keep the rider present but flag
            # the row; the engine refuses to commit until the file is fixed.
            payout_invalid = raw_text
            payout = 0.0
            warnings.append(
                f"{company}: rider {rider_id} has an unreadable payout cell "
                f"({raw_text!r}) — fix the file before committing"
            )
        cod = to_float(row.get(cod_col)) if cod_col else None
        orders_val = to_float(row.get(orders_col)) if orders_col else None

        def _cell(col):
            if not col:
                return None
            v = row.get(col)  # noqa: B023
            if v is None:
                return None
            s = str(v).strip()
            return s if s and s.lower() != "nan" else None

        records.append(
            RiderRecord(
                rider_id=rider_id,
                payout=to_paise(payout),
                cod_pending=to_paise(cod or 0),
                orders=orders_val,
                name=_cell(name_col),
                hub=_cell(hub_col),
                payout_invalid=payout_invalid,
            )
        )

    dupes = sorted(rid for rid, n in seen.items() if n > 1)
    if dupes:
        # A payout sheet is one row per rider. A repeated id (a subtotal band, a
        # pasted-twice block) would otherwise be PAID TWICE.
        shown = ", ".join(dupes[:10]) + (" …" if len(dupes) > 10 else "")
        raise ValueError(
            f"{company}: {len(dupes)} rider id(s) appear more than once on sheet "
            f"'{sheet}': {shown}. Each rider must have exactly one row — fix the file."
        )

    # ── Separate hold sheet (Jiffy style), found by content ──────────────────
    cod_lines: list[CodHoldLine] = []
    if config["has_hold_sheet"] and config["hold_style"] == "sheet":
        hold_sheet = _find_hold_sheet(xl, config)
        if hold_sheet is None:
            warnings.append(f"{company}: COD/hold sheet not found")
        else:
            hold_df = read_table(xl, hold_sheet, [config["hold_key_column"], "worker code"])
            cod_lines = _extract_cod_lines(hold_df, config, warnings)
            matched["hold_sheet"] = hold_sheet

    return ParseResult(
        company=company,
        records=records,
        cod_lines=cod_lines,
        warnings=warnings,
        sheet=sheet,
        matched_columns=matched,
    )


def _resolve_payout_sheet(xl: pd.ExcelFile, config: sqlite3.Row):
    """Find the payout sheet + DataFrame, robust to sheet reordering/renaming."""
    rid, pay = config["rider_id_column"], config["payout_column"]

    def has_cols(frame: pd.DataFrame) -> bool:
        return (
            match_column(frame.columns, rid, *_RIDER_ALIASES) is not None
            and match_column(frame.columns, pay) is not None
        )

    # 1. The configured selector, if it lands on a sheet with the right columns.
    try:
        sheet = select_sheet(xl, config["payout_sheet"])
        df = read_table(xl, sheet, [rid, *_RIDER_ALIASES])
        if has_cols(df):
            return sheet, df
    except ValueError:
        pass

    # 2. Content detection — survives sheet reordering / renaming.
    for name in xl.sheet_names:
        df = read_table(xl, name, [rid, *_RIDER_ALIASES])
        if has_cols(df):
            return name, df

    # 3. Last resort: configured selector (let the column checks raise a clear error).
    sheet = select_sheet(xl, config["payout_sheet"])
    return sheet, read_table(xl, sheet, [rid, *_RIDER_ALIASES])


def _find_hold_sheet(xl: pd.ExcelFile, config: sqlite3.Row) -> str | None:
    """Find the COD/hold sheet by the columns it contains (then by config)."""
    key, amt = config["hold_key_column"], config["hold_amount_column"]

    for name in xl.sheet_names:
        df = read_table(xl, name, [key, "worker code"])
        if (
            match_column(df.columns, key, "worker code") is not None
            and match_column(df.columns, amt, "amount") is not None
        ):
            return name

    if config["hold_sheet"]:
        try:
            return select_sheet(xl, config["hold_sheet"])
        except ValueError:
            return None
    return None


def _extract_cod_lines(
    df: pd.DataFrame, config: sqlite3.Row, warnings: list[str]
) -> list[CodHoldLine]:
    """Pull COD line items out of a hold-sheet DataFrame."""
    company = config["company_name"]
    key_col = match_column(df.columns, config["hold_key_column"], "worker code")
    amt_col = match_column(df.columns, config["hold_amount_column"], "amount")
    # Status: the configured column, else the usual header names. A COD sheet
    # that carries a status column but no config for it used to hold EVERY
    # line, settled ones included.
    status_col = match_column(
        df.columns,
        config["hold_status_column"],
        "transaction status",
        "txn status",
        "txn_status",
        "status",
    )
    order_col = match_column(df.columns, "order number", "order_number", "order no")
    mode_col = match_column(df.columns, "payment mode", "payment_mode")
    hub_col = match_column(df.columns, "hub code", "hub_code", *_HUB_ALIASES)
    name_col = match_column(df.columns, "worker name", "worker_name", *_NAME_ALIASES)

    if not key_col or not amt_col:
        warnings.append(f"{company}: hold sheet missing key/amount columns")
        return []

    def _text(row, col):
        if not col:
            return None
        v = row.get(col)
        if v is None:
            return None
        t = str(v).strip()
        return t if t and t.lower() != "nan" else None

    lines: list[CodHoldLine] = []
    for _, row in df.iterrows():
        # Same normalisation as the payout sheet: the worker code is the rider
        # id (a phone number at Spencer's) and must match the payout rows.
        worker_code = _normalise_rider_id(row.get(key_col, ""))
        if not worker_code:
            continue
        amount = to_float(row.get(amt_col))
        if amount is None:
            continue
        lines.append(
            CodHoldLine(
                worker_code=worker_code,
                amount=to_paise(amount),
                order_number=_text(row, order_col) or "" if order_col else None,
                payment_mode=_text(row, mode_col) or "" if mode_col else None,
                txn_status=_text(row, status_col) or "" if status_col else None,
                hub=_text(row, hub_col),
                name=_text(row, name_col),
            )
        )
    return lines
