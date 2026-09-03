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
    hub: str | None = None  # hub/store code as the COD sheet states it
    name: str | None = None  # worker name as the COD sheet states it


@dataclass
class HoldResult:
    per_rider: dict = field(default_factory=dict)  # rider_id -> total pending COD
    lines: list = field(default_factory=list)  # list[HoldLine] to persist
    skipped_nonpending: int = 0
    # rider_id -> {"name", "hub"} as the file states them (COD sheet first,
    # payout sheet as fallback). Lets the HOLD sheet label COD riders who are
    # not in the payout — and so may not be on the roster at all.
    rider_info: dict = field(default_factory=dict)

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
    info: dict[str, dict] = {}

    def _note(rider_id, name, hub):
        cur = info.setdefault(rider_id, {"name": None, "hub": None})
        cur["name"] = cur["name"] or name
        cur["hub"] = cur["hub"] or hub

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
                hub=cl.hub,
                name=cl.name,
            )
        )

    # Myntra style: inline COD-Pending on each rider record.
    for rec in parse_result.records:
        if rec.cod_pending and rec.cod_pending > 0:
            per_rider[rec.rider_id] = per_rider.get(rec.rider_id, 0.0) + rec.cod_pending
            lines.append(
                HoldLine(
                    rider_id=rec.rider_id,
                    amount=rec.cod_pending,
                    source="myntra_column",
                    hub=rec.hub,
                    name=rec.name,
                )
            )
    # Name/hub labels: the payout sheet is the primary source for riders in it;
    # the COD sheet labels everyone else (and fills any gaps).
    cod_ids = {cl.worker_code for cl in parse_result.cod_lines}
    for rec in parse_result.records:
        if rec.rider_id in per_rider or rec.rider_id in cod_ids:
            _note(rec.rider_id, rec.name, rec.hub)
    for cl in parse_result.cod_lines:
        _note(cl.worker_code, cl.name, cl.hub)

    return HoldResult(per_rider=per_rider, lines=lines, skipped_nonpending=skipped, rider_info=info)


def persist_holds(
    conn: sqlite3.Connection,
    company: str,
    cycle_start: date,
    cycle_end: date,
    hold_result: HoldResult,
) -> None:
    """Write the cycle's COD hold detail to the cod_holds table.

    Replaces whatever this (company, cycle) wrote before, so re-running a cycle
    (``force=true``) does not double the HOLD sheet's per-rider totals."""
    cs = cycle_start.isoformat() if hasattr(cycle_start, "isoformat") else str(cycle_start)
    ce = cycle_end.isoformat() if hasattr(cycle_end, "isoformat") else str(cycle_end)
    conn.execute(
        "DELETE FROM cod_holds WHERE company=? AND cycle_start=? AND cycle_end=?",
        (company, cs, ce),
    )
    for ln in hold_result.lines:
        pr = conn.execute(
            "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
            (ln.rider_id, company),
        ).fetchone()
        conn.execute(
            "INSERT INTO cod_holds (cycle_start, cycle_end, company, rider_id, "
            "person_id, worker_code, order_number, amount, payment_mode, txn_status, source, "
            "hub, worker_name) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                cs,
                ce,
                company,
                ln.rider_id,
                pr["person_id"] if pr else None,
                ln.rider_id,
                ln.order_number,
                ln.amount,
                ln.payment_mode,
                ln.txn_status,
                ln.source,
                ln.hub,
                ln.name,
            ),
        )
