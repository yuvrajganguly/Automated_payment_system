"""Domain data structures.

Plain dataclasses passed between the parsers, engine, and output builder.
The parsing-stage structures live here; cycle-result structures (PAY/DUES/etc.)
are added as the engine is built.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RiderRecord:
    """One rider row extracted from a company payout file."""

    rider_id: str
    payout: float
    cod_pending: float = 0.0  # inline COD (e.g. Myntra's COD-Pending); else 0


@dataclass
class CodHoldLine:
    """One COD line item from a separate hold sheet (e.g. Jiffy)."""

    worker_code: str
    amount: float
    order_number: str | None = None
    payment_mode: str | None = None
    txn_status: str | None = None


@dataclass
class ParseResult:
    """Normalised result of parsing one company file for one cycle."""

    company: str
    records: list[RiderRecord] = field(default_factory=list)
    cod_lines: list[CodHoldLine] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    sheet: str | None = None  # which sheet the payout was read from
    matched_columns: dict[str, str] = field(default_factory=dict)  # logical -> actual


@dataclass
class ParsePreview:
    """A non-committal summary of a parsed file, for the upload-preview UI.

    Lets the operator confirm what matched (and what was skipped) *before*
    anything is written, so format drift is caught at upload time.
    """

    company: str
    sheet: str | None
    matched_columns: dict[str, str]
    record_count: int
    total_payout: float
    cod_line_count: int
    total_cod: float
    warnings: list[str] = field(default_factory=list)
    sample: list[dict] = field(default_factory=list)
