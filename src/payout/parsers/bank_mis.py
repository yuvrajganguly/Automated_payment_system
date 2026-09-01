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

import pdfplumber

# Header columns observed in real reports — we match by substring so minor
# variations don't break parsing.
_HEADERS = {
    "mode": ["pymt_mode", "mode"],
    "bene_name": ["beneficia ry name", "beneficiary name"],
    "bene_acc": ["beneficia ry", "beneficiary account no"],
    "ifsc": ["bene_ifs c_code", "ifsc"],
    "amount": ["amount"],
    "remark": ["remark"],
    "date": ["pymt_da te", "pymt_date", "payment date"],
    "status": ["status"],
    "ref": ["custome r ref no", "customer ref no"],
    "utr": ["utr no", "utr"],
}


def _normalise(s: str | None) -> str:
    return (s or "").replace("\n", " ").strip()


def _column_indexes(header_row: list[str]) -> dict[str, int]:
    """Best-effort map: logical name → column index in this table.

    Two rules keep the substring aliases from colliding: the most specific
    aliases win first (every alias of every key is tried longest-first), and a
    column claimed by one key is never handed to another. Without that,
    ``"beneficia ry"`` (the wrapped account-number header) also matched
    ``"Beneficia ry Name"`` and the account number was read as the name.
    """
    out: dict[str, int] = {}
    cells = [(_normalise(c) or "").lower() for c in header_row]
    claimed: set[int] = set()
    candidates = sorted(
        ((len(alias), key, alias) for key, aliases in _HEADERS.items() for alias in aliases),
        reverse=True,
    )
    for _, key, alias in candidates:
        if key in out:
            continue
        for i, cell in enumerate(cells):
            if i not in claimed and alias in cell:
                out[key] = i
                claimed.add(i)
                break
    return out


def _stitch(rows: list[list[str | None]]) -> list[list[str]]:
    """Merge continuation rows (those whose first non-blank column is far
    right of left) into the previous row. pdfplumber emits one row per
    physical line so a wrapped cell becomes its own row with mostly empty
    cells — we glue it back."""
    stitched: list[list[str]] = []
    for raw in rows:
        cells = [_normalise(c) for c in raw]
        if not stitched:
            stitched.append(cells)
            continue
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


def _to_amount(s: str) -> int:
    """Amount cell -> integer paise (every other parser returns paise; this one
    returned rupee floats, which were then stored in the paise column)."""
    from payout.money import to_paise

    m = re.search(r"-?\d[\d,]*\.?\d*", s.replace(",", ""))
    return to_paise(float(m.group(0))) if m else 0


def parse_bank_mis(pdf_bytes: bytes) -> list[dict]:
    """Parse a bank MIS PDF into a list of beneficiary-line dicts.

    Multi-page handling: most reports only print the column header on page 1.
    Pages 2+ are pure data rows. We cache the column layout from the first
    page that successfully exposed one, and reuse it for every subsequent
    table whose own header row can't be detected. This keeps the page-2+
    rows from being silently dropped.
    """
    out: list[dict] = []
    line_no = 0
    cached_cols: dict[str, int] | None = None
    cached_col_count: int = 0
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            for table in tables:
                if not table or len(table) < 1:
                    continue
                # Try to detect a header row on this page.
                hdr_idx = next(
                    (
                        i
                        for i, row in enumerate(table)
                        if any("amount" in (_normalise(c) or "").lower() for c in row)
                    ),
                    None,
                )
                cols: dict[str, int] | None = None
                data_start = 0
                if hdr_idx is not None:
                    cols = _column_indexes(table[hdr_idx])
                    if "bene_acc" in cols and "amount" in cols:
                        cached_cols = cols
                        cached_col_count = len(table[hdr_idx])
                        data_start = hdr_idx + 1
                    else:
                        cols = None  # header didn't actually carry our anchors
                if cols is None:
                    # Continuation page (or detection failure). Fall back to
                    # the cached layout. Only reuse it if this table's row
                    # widths roughly match the page that originally exposed
                    # the layout — otherwise we'd map columns wrong.
                    if cached_cols is None:
                        continue
                    if cached_col_count and any(
                        abs(len(r) - cached_col_count) > 1 for r in table[:3]
                    ):
                        continue
                    cols = cached_cols
                    data_start = 0
                data_rows = _stitch(table[data_start:])
                for row in data_rows:

                    def cell(key):
                        i = cols.get(key)  # noqa: B023
                        return row[i] if i is not None and i < len(row) else ""  # noqa: B023

                    name = cell("bene_name")
                    acct = cell("bene_acc").replace(" ", "")
                    if not name and not acct:
                        continue
                    line_no += 1
                    out.append(
                        {
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
                        }
                    )
    return out
