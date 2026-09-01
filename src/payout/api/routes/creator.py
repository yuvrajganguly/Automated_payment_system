"""Creator-only super-admin endpoints.

These deliberately bypass the safety rails that admins are bound by.

  * audit_log read — only the creator can see who did what across the system.
  * system_stats   — DB size, row counts, last activity.
  * backup_download — streams the SQLite file as-is for offline copy.
  * delete_person — cascade-purges a person and every reference (transactions,
                     rider_master, balances, ev_arrears, ev_assignments, COD).
  * delete_ev     — purges an EV unit (and its assignments + maintenance).
  * delete_company — drops a company from the parser config (refuses if any
                     transactions still reference it; force=true bypasses).
  * edit_transaction / void_transaction — the only writable holes in the
                     append-only ledger. Recompute the person's balance after.
  * force_merge   — collapse two persons even when both hold open EVs; the
                     secondary's open EV is returned today before the move.
  * ev_models + companies CRUD — full create/edit/delete on parser config.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from payout.api.auth import require_creator
from payout.db import get_connection
from payout.db.references import purge_ev, purge_person, repoint_person
from payout.money import to_paise
from payout.config import DB_PATH as _DB_PATH

router = APIRouter()


# ── 1. Audit log ──────────────────────────────────────────────────────────
@router.get("/audit-log")
def audit_log(
    limit: int = Query(200, ge=1, le=1000),
    email: Optional[str] = None,
    method: Optional[str] = None,
    _: dict = Depends(require_creator),
) -> list[dict]:
    sql = ("SELECT id, at, email, role, method, path, status_code, "
           "       duration_ms, body_excerpt, ip "
           "FROM audit_log WHERE 1=1 ")
    params: list = []
    if email:
        sql += " AND email = ?"; params.append(email)
    if method:
        sql += " AND method = ?"; params.append(method.upper())
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ── 2. System stats ───────────────────────────────────────────────────────
@router.get("/system/stats")
def system_stats(_: dict = Depends(require_creator)) -> dict:
    db_path = str(_DB_PATH)
    db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
    with get_connection() as conn:
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in tables}
        last_cycle = conn.execute(
            "SELECT MAX(cycle_end) AS m FROM transactions"
        ).fetchone()["m"]
        last_audit = conn.execute(
            "SELECT MAX(at) AS m FROM audit_log"
        ).fetchone()["m"]
    return {
        "db_path": db_path,
        "db_size_bytes": db_size,
        "db_size_mb": round(db_size / (1024 * 1024), 2),
        "table_counts": counts,
        "last_cycle_end": last_cycle,
        "last_audit_at": last_audit,
    }


# ── 3. Backup ─────────────────────────────────────────────────────────────
@router.get("/system/backup")
def backup_download(_: dict = Depends(require_creator)) -> FileResponse:
    """Stream the SQLite file as a download. WAL pages are flushed first."""
    with get_connection() as conn:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
    return FileResponse(
        str(_DB_PATH),
        filename=f"payout-backup-{Path(_DB_PATH).stem}.sqlite",
        media_type="application/octet-stream",
    )


# ── 4. Hard delete a person ───────────────────────────────────────────────
@router.delete("/persons/{person_id}")
def delete_person(person_id: int,
                  cascade: bool = Query(True),
                  _: dict = Depends(require_creator)) -> dict:
    with get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM person_registry WHERE person_id=?", (person_id,)
        ).fetchone():
            raise HTTPException(404, "Person not found")
        if not cascade:
            raise HTTPException(
                400,
                "Cascade is required — there's no safe way to delete a person "
                "without dropping their riders/transactions/EV history too.",
            )
        # One canonical, FK-ordered list (db/references.py). The hand-rolled
        # list here missed ev_daily_ledger and deleted transactions before
        # payment_lines, so any person with ledger rows 500'd.
        purge_person(conn, person_id)
        conn.commit()
    return {"deleted": True, "person_id": person_id}


# ── 5. Hard delete an EV ──────────────────────────────────────────────────
@router.delete("/evs/{ev_id}")
def delete_ev(ev_id: str, _: dict = Depends(require_creator)) -> dict:
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM ev_units WHERE ev_id=?", (ev_id,)).fetchone():
            raise HTTPException(404, "EV not found")
        purge_ev(conn, ev_id)   # incl. ev_daily_ledger, which was forgotten here
        conn.commit()
    return {"deleted": True, "ev_id": ev_id}


# ── 6. Hard delete a company ──────────────────────────────────────────────
@router.delete("/companies/{name}")
def delete_company(name: str, force: bool = Query(False),
                   _: dict = Depends(require_creator)) -> dict:
    with get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM companies WHERE company_name=?", (name,)
        ).fetchone():
            raise HTTPException(404, "Company not found")
        ref = conn.execute(
            "SELECT COUNT(*) AS n FROM rider_master WHERE company=?", (name,)
        ).fetchone()["n"]
        if ref and not force:
            raise HTTPException(
                409,
                f"{ref} rider_master rows still reference {name!r}. "
                f"Pass force=true to drop them and the company, or migrate "
                f"those riders to another company first.",
            )
        if force:
            conn.execute("DELETE FROM transactions WHERE company=?", (name,))
            conn.execute("DELETE FROM cod_holds WHERE company=?", (name,))
            conn.execute("DELETE FROM rider_master WHERE company=?", (name,))
        conn.execute("DELETE FROM companies WHERE company_name=?", (name,))
        conn.commit()
    return {"deleted": True, "company": name, "forced": force}


# ── 7. Transaction surgery ────────────────────────────────────────────────
class TxnEditIn(BaseModel):
    amount: Optional[float] = None
    remarks: Optional[str] = None


def _rebalance(conn, person_id: int) -> float:
    """Recompute balances.current_balance from the surviving ledger."""
    row = conn.execute(
        "SELECT balance_after FROM transactions WHERE person_id=? "
        "ORDER BY id DESC LIMIT 1", (person_id,),
    ).fetchone()
    bal = float(row["balance_after"]) if row else 0.0
    conn.execute(
        "INSERT INTO balances (person_id, current_balance, last_updated) "
        "VALUES (?,?, date('now')) ON CONFLICT(person_id) DO UPDATE SET "
        "current_balance=excluded.current_balance, last_updated=excluded.last_updated",
        (person_id, bal),
    )
    return bal


@router.patch("/transactions/{txn_id}")
def edit_transaction(txn_id: int, body: TxnEditIn,
                     _: dict = Depends(require_creator)) -> dict:
    if body.amount is None and body.remarks is None:
        raise HTTPException(400, "Nothing to update")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT person_id, amount FROM transactions WHERE id=?", (txn_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Transaction not found")
        sets, params = [], []
        if body.amount is not None:
            delta = to_paise(body.amount) - float(row["amount"])
            sets.append("amount = ?"); params.append(to_paise(body.amount))
            sets.append("balance_after = balance_after + ?"); params.append(delta)
        if body.remarks is not None:
            sets.append("remarks = ?"); params.append(body.remarks)
        params.append(txn_id)
        conn.execute(f"UPDATE transactions SET {', '.join(sets)} WHERE id=?", params)
        new_balance = _rebalance(conn, row["person_id"])
        conn.commit()
    return {"updated": True, "transaction_id": txn_id, "new_balance": new_balance}


@router.delete("/transactions/{txn_id}")
def void_transaction(txn_id: int, _: dict = Depends(require_creator)) -> dict:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT person_id, event_type FROM transactions WHERE id=?", (txn_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "Transaction not found")
        # Demote any ev_daily_ledger rows that cite this transaction so they
        # don't end up with dangling references. Order matters:
        #   * Rows where THIS txn was the cycle event (RENT/RENT_MISSED) drop
        #     back to 'pending' so a future cycle can re-bill them.
        #   * Rows where THIS txn was the recovery event flip the cured days
        #     back to 'missed' so a later recovery can heal them again.
        conn.execute(
            "UPDATE ev_daily_ledger SET billing_status='pending', "
            "  cycle_event_id=NULL, last_updated=datetime('now') "
            "WHERE cycle_event_id=?",
            (txn_id,),
        )
        conn.execute(
            "UPDATE ev_daily_ledger SET billing_status='missed', "
            "  recovery_event_id=NULL, last_updated=datetime('now') "
            "WHERE recovery_event_id=?",
            (txn_id,),
        )
        conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
        new_balance = _rebalance(conn, row["person_id"])
        conn.commit()
    return {"voided": True, "transaction_id": txn_id, "new_balance": new_balance}


# ── 8. Force merge ────────────────────────────────────────────────────────
class ForceMergeIn(BaseModel):
    primary_person_id: int
    secondary_person_id: int


@router.post("/force-merge")
def force_merge(body: ForceMergeIn, _: dict = Depends(require_creator)) -> dict:
    """Merge two persons even if both have open EV assignments.

    The regular /persons/link route refuses when there's a conflict; this
    closes the secondary's open assignment as of today, then runs the merge.
    """
    if body.primary_person_id == body.secondary_person_id:
        raise HTTPException(400, "Same person.")
    with get_connection() as conn:
        for pid in (body.primary_person_id, body.secondary_person_id):
            if not conn.execute(
                "SELECT 1 FROM person_registry WHERE person_id=?", (pid,)
            ).fetchone():
                raise HTTPException(404, f"Person {pid} not found")
        # If primary already has an open EV, close secondary's.
        primary_open = conn.execute(
            "SELECT 1 FROM ev_assignments WHERE person_id=? AND returned_date IS NULL",
            (body.primary_person_id,),
        ).fetchone()
        if primary_open:
            conn.execute(
                "UPDATE ev_assignments SET returned_date=date('now') "
                "WHERE person_id=? AND returned_date IS NULL",
                (body.secondary_person_id,),
            )
        # Now reuse the same re-pointing as the normal merge.
        repoint_person(conn, body.secondary_person_id, body.primary_person_id)
        # Sum balances + arrears.
        bal = conn.execute(
            "SELECT current_balance FROM balances WHERE person_id=?",
            (body.secondary_person_id,),
        ).fetchone()
        if bal and bal["current_balance"]:
            conn.execute(
                "INSERT OR IGNORE INTO balances (person_id, current_balance) VALUES (?, 0)",
                (body.primary_person_id,),
            )
            conn.execute(
                "UPDATE balances SET current_balance = current_balance + ? WHERE person_id=?",
                (bal["current_balance"], body.primary_person_id),
            )
        arr = conn.execute(
            "SELECT total_missed, total_recovered, outstanding, "
            "       cod_missed, cod_recovered, cod_outstanding "
            "FROM ev_arrears WHERE person_id=?",
            (body.secondary_person_id,),
        ).fetchone()
        if arr:
            conn.execute(
                "INSERT OR IGNORE INTO ev_arrears (person_id) VALUES (?)",
                (body.primary_person_id,),
            )
            conn.execute(
                "UPDATE ev_arrears SET "
                "  total_missed    = total_missed    + ?, "
                "  total_recovered = total_recovered + ?, "
                "  outstanding     = outstanding     + ?, "
                "  cod_missed      = cod_missed      + ?, "
                "  cod_recovered   = cod_recovered   + ?, "
                "  cod_outstanding = cod_outstanding + ? "
                "WHERE person_id=?",
                (arr["total_missed"] or 0, arr["total_recovered"] or 0,
                 arr["outstanding"] or 0, arr["cod_missed"] or 0,
                 arr["cod_recovered"] or 0, arr["cod_outstanding"] or 0,
                 body.primary_person_id),
            )
        for t in ("balances", "ev_arrears", "status_tracking", "person_registry"):
            conn.execute(f"DELETE FROM {t} WHERE person_id=?",
                         (body.secondary_person_id,))
        conn.commit()
    return {"merged": True, "into_person_id": body.primary_person_id,
            "from_person_id": body.secondary_person_id}


# ── 9. EV model CRUD ──────────────────────────────────────────────────────
class EvModelIn(BaseModel):
    provider: str
    model_name: str
    weekly_rate: float


@router.post("/ev-models")
def create_ev_model(body: EvModelIn, _: dict = Depends(require_creator)) -> dict:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO ev_models (provider, model_name, weekly_rate) VALUES (?,?,?)",
            (body.provider, body.model_name, to_paise(body.weekly_rate)),
        )
        conn.commit()
        mid = cur.lastrowid
    return {"created": True, "model_id": mid}


@router.patch("/ev-models/{model_id}")
def edit_ev_model(model_id: int, body: EvModelIn,
                  _: dict = Depends(require_creator)) -> dict:
    with get_connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM ev_models WHERE model_id=?", (model_id,)
        ).fetchone():
            raise HTTPException(404, "Model not found")
        conn.execute(
            "UPDATE ev_models SET provider=?, model_name=?, weekly_rate=? "
            "WHERE model_id=?",
            (body.provider, body.model_name, to_paise(body.weekly_rate), model_id),
        )
        conn.commit()
    return {"updated": True, "model_id": model_id}


@router.delete("/ev-models/{model_id}")
def delete_ev_model(model_id: int, _: dict = Depends(require_creator)) -> dict:
    with get_connection() as conn:
        ref = conn.execute(
            "SELECT COUNT(*) AS n FROM ev_units WHERE model_id=?", (model_id,)
        ).fetchone()["n"]
        if ref:
            raise HTTPException(
                409,
                f"{ref} EV units still use this model. Migrate them first.",
            )
        conn.execute("DELETE FROM ev_models WHERE model_id=?", (model_id,))
        conn.commit()
    return {"deleted": True, "model_id": model_id}
