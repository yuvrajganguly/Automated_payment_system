"""COD hold handling.

Two input shapes produce the same outcome - a per-rider pending-COD total that
flags the rider HOLD and is recorded for audit:

  - Jiffy : a separate sheet of COD line items, summed per worker code. Only
            rows whose Transaction Status is pending (or blank) are counted.
  - Myntra: an inline COD-Pending column per rider.

A COD hold is a withhold flag plus a recorded amount for manual decision; it is
never auto-deducted from the payout.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date

from payout.domain.models import ParseResult

_PENDING = ("pending",)


@dataclass
class HoldLine:
    rider_id: str
    amount: float
    source: str  # 'jiffy_sheet' | 'myntra_column'
    order_number: str | None = None
    payment_mode: str | None = None
    txn_status: str | None = None


@dataclass
class HoldResult:
    per_rider: dict = field(default_factory=dict)  # rider_id -> total pending COD
    lines: list = field(default_factory=list)      # list[HoldLine] to persist
    skipped_nonpending: int = 0

    @property
    def held_rider_ids(self) -> set:
        return {rid for rid, amt in self.per_rider.items() if amt > 0}

    @property
    def total(self) -> float:
        return sum(self.per_rider.values())


def _is_pending(status, pending_statuses) -> bool:
    if status is None or str(status).strip() == "":
        return True
    return str(status).strip().lower() in pending_statuses


def compute_holds(parse_result: ParseResult, pending_statuses=_PENDING) -> HoldResult:
    """Roll a parsed file's COD data into per-rider hold totals + line detail."""
    per_rider: dict[str, float] = {}
    lines: list[HoldLine] = []
    skipped = 0

    # Jiffy style: separate COD line items keyed by worker code (== rider id).
    for cl in parse_result.cod_lines:
        if not _is_pending(cl.txn_status, pending_statuses):
            skipped += 1
            continue
        per_rider[cl.worker_code] = per_rider.get(cl.worker_code, 0.0) + cl.amount
        lines.append(
            HoldLine(
                rider_id=cl.worker_code,
                amount=cl.amount,
                source="jiffy_sheet",
                order_number=cl.order_number,
                payment_mode=cl.payment_mode,
                txn_status=cl.txn_status,
            )
        )

    # Myntra style: inline COD-Pending on each rider record.
    for rec in parse_result.records:
        if rec.cod_pending and rec.cod_pending > 0:
            per_rider[rec.rider_id] = per_rider.get(rec.rider_id, 0.0) + rec.cod_pending
            lines.append(HoldLine(rider_id=rec.rider_id, amount=rec.cod_pending, source="myntra_column"))

    return HoldResult(per_rider=per_rider, lines=lines, skipped_nonpending=skipped)


def persist_holds(
    conn: sqlite3.Connection,
    company: str,
    cycle_start: date,
    cycle_end: date,
    hold_result: HoldResult,
) -> None:
    """Write the cycle's COD hold detail to the cod_holds table."""
    cs = cycle_start.isoformat() if hasattr(cycle_start, "isoformat") else str(cycle_start)
    ce = cycle_end.isoformat() if hasattr(cycle_end, "isoformat") else str(cycle_end)
    for ln in hold_result.lines:
        pr = conn.execute(
            "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
            (ln.rider_id, company),
        ).fetchone()
        conn.execute(
            "INSERT INTO cod_holds (cycle_start, cycle_end, company, rider_id, "
            "person_id, worker_code, order_number, amount, payment_mode, txn_status, source) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (cs, ce, company, ln.rider_id, pr["person_id"] if pr else None,
             ln.rider_id, ln.order_number, ln.amount, ln.payment_mode, ln.txn_status, ln.source),
        )
