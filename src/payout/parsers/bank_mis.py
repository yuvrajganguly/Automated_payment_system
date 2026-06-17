"""Parser for bank MIS reports (the Excel/PDF the bank produces after a
batch transfer run). Each beneficiary line carries the recipient's name,
account, IFSC, amount, status, and the bank's UTR / customer reference.

Returns a list of dicts ready to insert into ``payment_lines``. Matching
against the rider roster is done by the route handler so the parser stays
pure (no DB dependency).

The bank's PDF wraps cells across multiple physical lines when the
beneficiary name is long, so we use pdfplumber's table extractor and
explicitly re-stitch any row whose first cell is blank into the preceding
row's cell values.
"""

from __future__ import annotations

import io
import re
from typing import Optional

import pdfplumber


# Header columns observed in real reports — we match by substring so minor
# variations don't break parsing.
_HEADERS = {
    "mode":      ["pymt_mode", "mode"],
    "bene_name": ["beneficia ry name", "beneficiary name"],
    "bene_acc":  ["beneficia ry", "beneficiary account no"],
    "ifsc":      ["bene_ifs c_code", "ifsc"],
    "amount":    ["amount"],
    "remark":    ["remark"],
    "date":      ["pymt_da te", "pymt_date", "payment date"],
    "status":    ["status"],
    "ref":       ["custome r ref no", "customer ref no"],
    "utr":       ["utr no", "utr"],
}


def _normalise(s: Optional[str]) -> str:
    return (s or "").replace("\n", " ").strip()


def _column_indexes(header_row: list[str]) -> dict[str, int]:
    """Best-effort map: logical name → column index in this table."""
    out: dict[str, int] = {}
    cells = [(_normalise(c) or "").lower() for c in header_row]
    for key, aliases in _HEADERS.items():
        for i, cell in enumerate(cells):
            if any(alias in cell for alias in aliases):
                out[key] = i; break
    return out


def _stitch(rows: list[list[Optional[str]]]) -> list[list[str]]:
    """Merge continuation rows (those whose first non-blank column is far
    right of left) into the previous row. pdfplumber emits one row per
    physical line so a wrapped cell becomes its own row with mostly empty
    cells — we glue it back."""
    stitched: list[list[str]] = []
    for raw in rows:
        cells = [_normalise(c) for c in raw]
        if not stitched:
            stitched.append(cells); continue
        # A continuation row has very few non-empty cells AND those cells
        # are typically in the wider columns (name, account). Heuristic:
        # if more than half the cells are empty, treat as continuation.
        non_empty = [c for c in cells if c]
        if len(non_empty) < max(2, len(cells) // 2):
            for i, c in enumerate(cells):
                if c:
                    stitched[-1][i] = (stitched[-1][i] + " " + c).strip()
            continue
        stitched.append(cells)
    return stitched


def _to_amount(s: str) -> float:
    m = re.search(r"-?\d[\d,]*\.?\d*", s.replace(",", ""))
    return float(m.group(0)) if m else 0.0


def parse_bank_mis(pdf_bytes: bytes) -> list[dict]:
    """Parse a bank MIS PDF into a list of beneficiary-line dicts."""
    out: list[dict] = []
    line_no = 0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            for table in tables:
                if not table or len(table) < 2:
                    continue
                # Header may take multiple rows; find the row that actually
                # mentions "Amount" and treat everything above it as title.
                hdr_idx = next(
                    (i for i, row in enumerate(table)
                     if any("amount" in (_normalise(c) or "").lower() for c in row)),
                    0,
                )
                header_row = table[hdr_idx]
                cols = _column_indexes(header_row)
                if "bene_acc" not in cols or "amount" not in cols:
                    continue
                data_rows = _stitch(table[hdr_idx + 1:])
                for row in data_rows:
                    def cell(key):
                        i = cols.get(key)
                        return row[i] if i is not None and i < len(row) else ""
                    name = cell("bene_name")
                    acct = cell("bene_acc").replace(" ", "")
                    if not name and not acct:
                        continue
                    line_no += 1
                    out.append({
                        "line_no": line_no,
                        "pymt_mode": cell("mode"),
                        "bene_name": name,
                        "bene_account_no": acct,
                        "bene_ifsc": cell("ifsc").replace(" ", ""),
                        "amount": _to_amount(cell("amount")),
                        "remark": cell("remark"),
                        "pymt_date": cell("date"),
                        "bank_status": cell("status"),
                        "customer_ref": cell("ref"),
                        "utr": cell("utr"),
                    })
    return out
