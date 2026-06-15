"""Company payout-file parsers.

Public entry points:
  - parse_file    — parse a company file into a normalised ParseResult.
  - preview_file  — a non-committal summary for the upload-preview UI.

Parsing is config-driven — each company's behaviour comes from its companies
row — so adding a company needs no new code. A parser_type override hook is
kept for the rare file a config can't describe.
"""

from __future__ import annotations

import sqlite3

from payout.db import get_connection
from payout.domain.models import ParsePreview, ParseResult
from payout.parsers.generic import parse_with_config

# Optional per-type overrides for files a config can't fully describe.
# Maps companies.parser_type -> callable(file_bytes, config) -> ParseResult.
_OVERRIDES: dict[str, object] = {}


def _load_company_config(company_name: str) -> sqlite3.Row:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM companies WHERE company_name = ? AND is_active = 1",
            (company_name,),
        ).fetchone()
    if not row:
        raise ValueError(f"Company '{company_name}' not found or not active.")
    return row


def parse_file(company_name: str, file_bytes: bytes) -> ParseResult:
    """Parse a company's payout file into a normalised ParseResult."""
    config = _load_company_config(company_name)
    override = _OVERRIDES.get(config["parser_type"])
    if override is not None:
        return override(file_bytes, config)
    return parse_with_config(file_bytes, config)


def preview_file(
    company_name: str, file_bytes: bytes, sample_size: int = 5
) -> ParsePreview:
    """Summarise what a file *would* import, without writing anything."""
    result = parse_file(company_name, file_bytes)
    total_payout = sum(r.payout for r in result.records)
    total_cod = sum(r.cod_pending for r in result.records) + sum(
        c.amount for c in result.cod_lines
    )
    sample = [
        {"rider_id": r.rider_id, "payout": r.payout, "cod_pending": r.cod_pending}
        for r in result.records[:sample_size]
    ]
    return ParsePreview(
        company=result.company,
        sheet=result.sheet,
        matched_columns=result.matched_columns,
        record_count=len(result.records),
        total_payout=total_payout,
        cod_line_count=len(result.cod_lines),
        total_cod=total_cod,
        warnings=result.warnings,
        sample=sample,
    )


__all__ = ["parse_file", "preview_file", "parse_with_config"]
