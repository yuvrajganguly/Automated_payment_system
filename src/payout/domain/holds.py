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

import re
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
    hub: str | None = None  # hub NAME — the code resolved when the map knows it
    hub_code: str | None = None  # hub/store code exactly as the COD sheet states it
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


def _split_multi(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"[,;/|]", text) if p.strip()]


def hub_names_from_file(parse_result: ParseResult) -> dict[str, str]:
    """code (lower-cased) → hub name, from payout rows that carry both.

    A rider working two stores has "e005, s111" / "Marlin, Tolly DS" — the
    lists are paired up position by position when their lengths agree."""
    out: dict[str, str] = {}
    for rec in parse_result.records:
        codes = _split_multi(rec.hub_code or "")
        names = _split_multi(rec.hub or "")
        if not codes or not names:
            continue
        if len(codes) != len(names):
            if len(codes) == 1:
                names = [(rec.hub or "").strip()]
            else:
                continue  # can't tell which name goes with which code
        for code, name in zip(codes, names, strict=True):
            code = code.lower()
            if name and name.lower() != code:
                out[code] = name
    return out


def resolve_hub(raw: str | None, hub_names: dict[str, str] | None) -> str | None:
    """The hub name for a COD-sheet hub cell: the mapped name when the code is
    known ("H012" → "South City"), else the cell as written."""
    if not raw:
        return raw
    if hub_names:
        return hub_names.get(raw.strip().lower(), raw)
    return raw


def compute_holds(
    parse_result: ParseResult,
    pending_statuses=_PENDING,
    hub_names: dict[str, str] | None = None,
) -> HoldResult:
    """Roll a parsed file's COD data into per-rider hold totals + line detail.

    ``hub_names`` maps hub CODES to names (this file's own store_ids →
    store_names pairs merged with what earlier files taught); COD sheets only
    state the code."""
    hub_names = {**hub_names_from_file(parse_result), **(hub_names or {})}
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
                hub=resolve_hub(cl.hub, hub_names),
                hub_code=cl.hub,
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
        _note(cl.worker_code, cl.name, resolve_hub(cl.hub, hub_names))

    return HoldResult(per_rider=per_rider, lines=lines, skipped_nonpending=skipped, rider_info=info)


def load_hub_names(conn: sqlite3.Connection, company: str) -> dict[str, str]:
    """code → name learnt from earlier files of this company (hub_codes)."""
    return {
        r["code"]: r["name"]
        for r in conn.execute(
            "SELECT code, name FROM hub_codes WHERE company=?", (company,)
        ).fetchall()
    }


def learn_hub_names(conn: sqlite3.Connection, company: str, pairs: dict[str, str]) -> None:
    """Remember this file's code → name pairs; the latest file wins."""
    for code, name in pairs.items():
        conn.execute(
            "INSERT INTO hub_codes (company, code, name, updated_at) "
            "VALUES (?,?,?,datetime('now')) "
            "ON CONFLICT(company, code) DO UPDATE SET name=excluded.name, "
            "updated_at=excluded.updated_at",
            (company, code, name),
        )


def persist_holds(
    conn: sqlite3.Connection,
    company: str,
    cycle_start: date,
    cycle_end: date,
    hold_result: HoldResult,
) -> None:
    """Write the cycle's COD hold detail to the cod_holds table.

    Replaces whatever this (company, cycle) wrote before, so re-running a cycle
    (``force=true``) does not double the HOLD sheet's per-rider totals.

    What was already collected survives the rewrite: a row matching an old one
    (same rider, order and amount) keeps its ``paid`` and cleared stamp, and
    any part-payment left over from rows that changed is re-spread over the
    rider's new rows oldest first — re-running a cycle must not un-collect
    cash the office already holds."""
    cs = cycle_start.isoformat() if hasattr(cycle_start, "isoformat") else str(cycle_start)
    ce = cycle_end.isoformat() if hasattr(cycle_end, "isoformat") else str(cycle_end)
    old = conn.execute(
        "SELECT rider_id, order_number, amount, COALESCE(paid, 0) AS paid, "
        "       cleared_at, cleared_by "
        "FROM cod_holds WHERE company=? AND cycle_start=? AND cycle_end=? ORDER BY id",
        (company, cs, ce),
    ).fetchall()
    exact: dict[tuple, list] = {}
    for o in old:
        exact.setdefault((o["rider_id"], o["order_number"] or "", int(o["amount"])), []).append(o)
    conn.execute(
        "DELETE FROM cod_holds WHERE company=? AND cycle_start=? AND cycle_end=?",
        (company, cs, ce),
    )
    carried: list[tuple] = []  # (rider_id, amount, paid, cleared_at, cleared_by)
    for ln in hold_result.lines:
        match = exact.get((ln.rider_id, ln.order_number or "", int(ln.amount)))
        o = match.pop(0) if match else None
        carried.append(
            (
                ln.rider_id,
                int(ln.amount),
                int(o["paid"]) if o else 0,
                o["cleared_at"] if o else None,
                o["cleared_by"] if o else None,
            )
        )
    # Part-payments on rows that did not come back: spread over the rider's
    # new rows that are still open.
    leftover: dict[str, int] = {}
    for rows in exact.values():
        for o in rows:
            if o["paid"] and not o["cleared_at"]:
                leftover[o["rider_id"]] = leftover.get(o["rider_id"], 0) + int(o["paid"])
    for i, (rid, amt, paid, cat, cby) in enumerate(carried):
        extra = leftover.get(rid, 0)
        if extra and not cat:
            take = min(extra, amt - paid)
            leftover[rid] = extra - take
            carried[i] = (rid, amt, paid + take, cat, cby)
    for ln, (_rid, _amt, paid, cleared_at, cleared_by) in zip(
        hold_result.lines, carried, strict=True
    ):
        if paid >= int(ln.amount) and not cleared_at and int(ln.amount) > 0:
            cleared_at, cleared_by = date.today().isoformat(), "cod-payment"
        pr = conn.execute(
            "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
            (ln.rider_id, company),
        ).fetchone()
        conn.execute(
            "INSERT INTO cod_holds (cycle_start, cycle_end, company, rider_id, "
            "person_id, worker_code, order_number, amount, payment_mode, txn_status, source, "
            "hub, hub_code, worker_name, paid, cleared_at, cleared_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                ln.hub_code,
                ln.name,
                paid,
                cleared_at,
                cleared_by,
            ),
        )


class CodPaymentError(ValueError):
    """A COD payment that cannot be applied (nothing owed, or more than owed)."""


def apply_cod_payment(
    conn: sqlite3.Connection,
    person_id: int,
    amount: int,
    *,
    paid_on: str,
    created_by: str,
    note: str | None = None,
    entry_ids: list[int] | None = None,
) -> dict:
    """Record ``amount`` paise of COD collected from a person — all or part of
    what they hold — and spread it over their open cod_holds rows, oldest
    cycle first (or over ``entry_ids`` only, when given).

    A row is cleared once its ``paid`` reaches its ``amount``; a row the money
    only reaches part of stays open with the rest still owed. Paying more than
    is owed is refused rather than silently turned into a credit: COD is not on
    the ledger, so an excess would have nowhere honest to go.

    Returns {payment_id, amount_applied, cod_still_owed, entries_cleared,
    entries_touched} (paise).
    """
    amount = int(amount)
    if amount <= 0:
        raise CodPaymentError("Amount must be positive")
    sql = (
        "SELECT id, amount, COALESCE(paid, 0) AS paid FROM cod_holds "
        "WHERE person_id=? AND cleared_at IS NULL AND amount > COALESCE(paid, 0)"
    )
    params: list = [person_id]
    if entry_ids:
        sql += f" AND id IN ({','.join('?' * len(entry_ids))})"
        params += list(entry_ids)
    rows = conn.execute(sql + " ORDER BY cycle_end, cycle_start, id", params).fetchall()
    owed = sum(int(r["amount"]) - int(r["paid"]) for r in rows)
    if owed <= 0:
        raise CodPaymentError("Nothing is owed on the selected COD")
    if amount > owed:
        raise CodPaymentError(
            f"Rs.{amount / 100:,.2f} is more than the Rs.{owed / 100:,.2f} still owed"
        )
    cur = conn.execute(
        "INSERT INTO cod_payments (person_id, amount, paid_on, note, created_by) "
        "VALUES (?,?,?,?,?)",
        (person_id, amount, paid_on, (note or "").strip() or None, created_by),
    )
    payment_id = cur.lastrowid
    left = amount
    cleared = touched = 0
    for r in rows:
        if left <= 0:
            break
        due = int(r["amount"]) - int(r["paid"])
        take = min(due, left)
        left -= take
        touched += 1
        if take == due:
            cleared += 1
            conn.execute(
                "UPDATE cod_holds SET paid=amount, cleared_at=?, cleared_by=? WHERE id=?",
                (paid_on, created_by, r["id"]),
            )
        else:
            conn.execute(
                "UPDATE cod_holds SET paid=COALESCE(paid, 0) + ? WHERE id=?", (take, r["id"])
            )
    return {
        "payment_id": payment_id,
        "amount_applied": amount,
        "cod_still_owed": owed - amount,
        "entries_cleared": cleared,
        "entries_touched": touched,
    }
