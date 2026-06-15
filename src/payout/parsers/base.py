"""Helpers shared by the Excel parsers."""

from __future__ import annotations

import re

import pandas as pd

# First numeric token in a string: optional sign, digits, commas, decimals.
# Tolerates currency symbols and stray text around the number (e.g. "₹1,200/-").
_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


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
    """Parse a value to float, tolerating commas, currency symbols and text.

    "₹1,200.50" -> 1200.5, "1,000" -> 1000, "Rs. 800/-" -> 800, "abc" -> None.
    """
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return None
    match = _NUMBER_RE.search(str(val).strip())
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


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


def read_table(
    xl: pd.ExcelFile, sheet: str, anchor_candidates, max_scan: int = 15
) -> pd.DataFrame:
    """Read a sheet, auto-detecting the header row.

    Some files put a title/banner row above the real headers. We scan the first
    ``max_scan`` rows for the first one that contains an anchor column name
    (e.g. the rider-id column) and treat that as the header. Falls back to row 0.
    """
    probe = xl.parse(sheet, header=None, dtype=str, nrows=max_scan)
    anchors = {str(a).strip().lower() for a in anchor_candidates if a}
    header_row = 0
    for i in range(len(probe)):
        cells = {str(v).strip().lower() for v in probe.iloc[i].tolist()}
        if anchors & cells:
            header_row = i
            break
    return normalise_columns(xl.parse(sheet, header=header_row, dtype=str))
