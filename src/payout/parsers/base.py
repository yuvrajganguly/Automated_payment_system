"""Helpers shared by the Excel parsers."""

from __future__ import annotations

import re

import pandas as pd

# A whole cell that is a money amount: optional currency marker (₹, Rs, Rs., INR),
# optional sign or accounting parentheses, digits with optional thousands commas
# and decimals, optional "/-" suffix. Anything else is NOT a number — the old
# "first numeric token" approach read '12-05-2026' as 12, 'abc123' as 123 and
# '1e3' as 1, silently turning junk cells into small payouts.
_MONEY_RE = re.compile(
    r"""^\s*
        (?P<paren>\()?\s*
        (?P<sign>[-+])?\s*
        (?:₹|rs\.?|inr)?\s*
        (?P<sign2>[-+])?\s*
        (?P<num>(?:\d{1,3}(?:,\d{2,3})+|\d+)(?:\.\d+)?|\.\d+)\s*
        (?:/-)?\s*
        (?(paren)\))\s*$""",
    re.IGNORECASE | re.VERBOSE,
)


def normalise_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Strip surrounding whitespace from every column name."""
    df.columns = [str(c).strip() for c in df.columns]
    return df


def match_column(columns, *candidates: str | None) -> str | None:
    """Return the real column name matching any candidate (case-insensitive)."""
    lower = {str(c).strip().lower(): c for c in columns}
    for cand in candidates:
        if cand and str(cand).strip().lower() in lower:
            return lower[str(cand).strip().lower()]
    return None


def find_column(df: pd.DataFrame, *candidates: str | None) -> str | None:
    """Convenience wrapper of :func:`match_column` for a DataFrame."""
    return match_column(df.columns, *candidates)


def to_float(val) -> float | None:
    """Parse a money cell to float; ``None`` when the cell is not a number.

    "₹1,200.50" -> 1200.5, "1,000" -> 1000, "Rs. 800/-" -> 800, "(500)" -> -500,
    "-75" -> -75.  "abc", "N/A", "12-05-2026", "1e3", "" -> None.
    """
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return None if (isinstance(val, float) and pd.isna(val)) else float(val)
    text = str(val).strip()
    if not text or text.lower() in ("nan", "none", "null", "na", "n/a", "-"):
        return None
    m = _MONEY_RE.match(text)
    if not m:
        return None
    try:
        value = float(m.group("num").replace(",", ""))
    except ValueError:
        return None
    if m.group("paren") or m.group("sign") == "-" or m.group("sign2") == "-":
        value = -value
    return value


def select_sheet(xl: pd.ExcelFile, selector: str | None) -> str:
    """Resolve a sheet selector to an actual sheet name.

    Selector forms:
      - ``None``           → first sheet
      - ``"0"`` / ``"1"``  → sheet by index
      - ``"pattern:foo"``  → first sheet whose name contains ``foo`` (ci)
      - ``"Exact Name"``   → that exact sheet
    """
    names = xl.sheet_names
    if not selector:
        return names[0]
    if selector.startswith("pattern:"):
        needle = selector.split("pattern:", 1)[1].strip().lower()
        for name in names:
            if needle in name.lower():
                return name
        raise ValueError(f"No sheet matching pattern '{needle}'. Sheets: {names}")
    if selector.isdigit():
        idx = int(selector)
        if idx >= len(names):
            raise ValueError(f"Sheet index {idx} out of range. Sheets: {names}")
        return names[idx]
    if selector in names:
        return selector
    raise ValueError(f"Sheet '{selector}' not found. Sheets: {names}")


def read_table(xl: pd.ExcelFile, sheet: str, anchor_candidates, max_scan: int = 15) -> pd.DataFrame:
    """Read a sheet, auto-detecting the header row.

    Some files put a title/banner row above the real headers. We scan the first
    ``max_scan`` rows for the first one that contains an anchor column name
    (e.g. the rider-id column) and treat that as the header. Falls back to row 0.
    """
    # keep_default_na=False: we want the cell's actual text. pandas would
    # otherwise turn "N/A", "NA", "null", "-" into NaN and we could no longer
    # tell "blank" from "junk" when reporting an unreadable payout.
    probe = xl.parse(sheet, header=None, dtype=str, nrows=max_scan, keep_default_na=False)
    anchors = {str(a).strip().lower() for a in anchor_candidates if a}
    header_row = 0
    for i in range(len(probe)):
        cells = {str(v).strip().lower() for v in probe.iloc[i].tolist()}
        if anchors & cells:
            header_row = i
            break
    return normalise_columns(xl.parse(sheet, header=header_row, dtype=str, keep_default_na=False))
