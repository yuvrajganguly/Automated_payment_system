"""Bank MIS reconciliation.

Operator workflow:
  1. After running a payout cycle and pushing the file to the bank, the bank
     returns an MIS report (PDF) listing each beneficiary transfer with a
     Success/Failed status, the bank's UTR, the timestamp.
  2. Operator uploads that PDF here. We parse it, match each line to a person
     by (account_no, ifsc) — falling back to fuzzy name match — and stash
     everything in payment_lines.
  3. Successful lines need no action. Failed/Unmatched lines need a decision:
       * 'upi_paid'      — operator paid the rider via UPI QR. No ledger
                           movement; just record the resolution.
       * 'credit_ledger' — bank transfer failed and we did NOT pay the rider.
                           Reverse the original release by crediting the
                           rider's balance, so the amount carries to next cycle.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel

from payout.api.auth import get_current_user, require_admin
from payout.db import get_connection
from payout.domain.adjustments import post_adjustment
from payout.parsers.bank_mis import parse_bank_mis

router = APIRouter()


def _norm_name(s: Optional[str]) -> str:
    return " ".join((s or "").strip().lower().split())


def _match_line(conn, acct: str, ifsc: str, name: str) -> tuple[Optional[int], Optional[str], str]:
    """Return (person_id, matched_display_name, match_status).
    Primary: account_no+ifsc → rider_master.person_id.
    Secondary: account_no alone → rider_master.person_id.
    Fallback: fuzzy name match (case-insensitive equality of display_name).
    """
    if acct:
        row = conn.execute(
            "SELECT DISTINCT rm.person_id, pr.display_name FROM rider_master rm "
            "JOIN person_registry pr ON pr.person_id = rm.person_id "
            "WHERE rm.account_no = ? AND (?='' OR rm.ifsc = ?) LIMIT 1",
            (acct, ifsc, ifsc),
        ).fetchone()
        if row:
            return row["person_id"], row["display_name"], "matched"
        # account-only match (IFSC may have been mistyped at one end)
        row = conn.execute(
            "SELECT DISTINCT rm.person_id, pr.display_name FROM rider_master rm "
            "JOIN person_registry pr ON pr.person_id = rm.person_id "
            "WHERE rm.account_no = ? LIMIT 1", (acct,),
        ).fetchone()
        if row:
            return row["person_id"], row["display_name"], "matched"
    # Name fallback
    nm = _norm_name(name)
    if nm:
        row = conn.execute(
            "SELECT person_id, display_name FROM person_registry "
            "WHERE LOWER(display_name) = ? LIMIT 1", (nm,),
        ).fetchone()
        if row:
            return row["person_id"], row["display_name"], "name_matched"
    return None, None, "unmatched"


@router.post("/upload")
async def upload_mis(
    file: UploadFile = File(...),
    user: dict = Depends(require_admin),
) -> dict:
    """Parse a bank MIS PDF and stash every line into payment_lines."""
    pdf_bytes = await file.read()
    try:
        lines = parse_bank_mis(pdf_bytes)
    except Exception as e:
        raise HTTPException(400, f"Couldn't parse PDF: {e}")
    if not lines:
        raise HTTPException(400, "No beneficiary lines found in this PDF.")

    success_count = failed_count = unmatched_count = 0
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO payment_uploads (file_name, uploaded_by, line_count) "
            "VALUES (?,?,0)", (file.filename or "upload.pdf", user["email"]),
        )
        upload_id = cur.lastrowid

        for ln in lines:
            pid, mname, match = _match_line(
                conn, ln["bene_account_no"], ln["bene_ifsc"], ln["bene_name"],
            )
            bank_status = (ln["bank_status"] or "").strip()
            is_success = bank_status.lower().startswith("success")
            if is_success:
                success_count += 1
                resolution = "bank_ok"   # auto-resolved
                resolved_at = date.today().isoformat()
                resolved_by = "auto"
            else:
                resolution = None
                resolved_at = None
                resolved_by = None
                failed_count += 1
            if match == "unmatched":
                unmatched_count += 1
            conn.execute(
                "INSERT INTO payment_lines "
                "(upload_id, line_no, pymt_mode, bene_name, bene_account_no, "
                " bene_ifsc, amount, remark, pymt_date, bank_status, utr, "
                " customer_ref, person_id, matched_name, match_status, "
                " resolution_method, resolved_at, resolved_by) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (upload_id, ln["line_no"], ln["pymt_mode"], ln["bene_name"],
                 ln["bene_account_no"], ln["bene_ifsc"], ln["amount"], ln["remark"],
                 ln["pymt_date"], bank_status, ln["utr"], ln["customer_ref"],
                 pid, mname, match, resolution, resolved_at, resolved_by),
            )
        conn.execute(
            "UPDATE payment_uploads SET line_count=?, success_count=?, "
            "failed_count=?, unmatched_count=? WHERE id=?",
            (len(lines), success_count, failed_count, unmatched_count, upload_id),
        )
        conn.commit()
    return {
        "upload_id": upload_id, "line_count": len(lines),
        "success_count": success_count, "failed_count": failed_count,
        "unmatched_count": unmatched_count,
    }


@router.get("/uploads")
def list_uploads(_: dict = Depends(get_current_user)) -> list[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, file_name, uploaded_at, uploaded_by, line_count, "
            "       success_count, failed_count, unmatched_count, notes "
            "FROM payment_uploads ORDER BY uploaded_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/uploads/{upload_id}")
def get_upload(upload_id: int, _: dict = Depends(get_current_user)) -> dict:
    with get_connection() as conn:
        u = conn.execute(
            "SELECT * FROM payment_uploads WHERE id=?", (upload_id,)
        ).fetchone()
        if not u:
            raise HTTPException(404, "Upload not found")
        lines = conn.execute(
            "SELECT id, line_no, pymt_mode, bene_name, bene_account_no, bene_ifsc, "
            "       amount, remark, pymt_date, bank_status, utr, customer_ref, "
            "       person_id, matched_name, match_status, resolution_method, "
            "       resolved_at, resolved_by "
            "FROM payment_lines WHERE upload_id=? ORDER BY line_no",
            (upload_id,),
        ).fetchall()
    return {"upload": dict(u), "lines": [dict(r) for r in lines]}


class ResolveIn(BaseModel):
    method: str  # 'upi_paid' or 'credit_ledger'
    note: Optional[str] = None


@router.post("/lines/{line_id}/resolve")
def resolve_line(line_id: int, body: ResolveIn,
                 user: dict = Depends(require_admin)) -> dict:
    """Mark a failed/unmatched line as resolved.

    * upi_paid       — no ledger movement; just record the resolution. Use
                       when you paid the rider via UPI QR.
    * credit_ledger  — credit the rider's balance by the failed amount.
                       Use when the bank transfer failed and you did NOT pay
                       — the amount now sits on their balance as money owed
                       to them, which the next cycle's release picks up.
    """
    if body.method not in ("upi_paid", "credit_ledger"):
        raise HTTPException(400, "method must be 'upi_paid' or 'credit_ledger'")
    with get_connection() as conn:
        line = conn.execute(
            "SELECT id, person_id, amount, bene_name, bank_status, "
            "       resolution_method, upload_id "
            "FROM payment_lines WHERE id=?", (line_id,),
        ).fetchone()
        if not line:
            raise HTTPException(404, "Line not found")
        if line["resolution_method"] and line["resolution_method"] != "bank_ok":
            raise HTTPException(
                409,
                f"Line already resolved as {line['resolution_method']}",
            )
        txn_id = None
        if body.method == "credit_ledger":
            if not line["person_id"]:
                raise HTTPException(
                    400,
                    "Can't credit ledger — this line isn't matched to a rider. "
                    "Open the rider's profile and post an Adjustment manually, "
                    "or merge them in first.",
                )
            reason = body.note or (
                f"Bank transfer failed (status={line['bank_status']!r}); "
                f"amount carried forward."
            )
            post_adjustment(
                conn, line["person_id"], float(line["amount"]),
                reason, user["email"], rider_id="", company="",
            )
            txn_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.execute(
            "UPDATE payment_lines SET resolution_method=?, resolved_at=date('now'), "
            "resolved_by=?, transaction_id=? WHERE id=?",
            (body.method, user["email"], txn_id, line_id),
        )
        # Refresh aggregate counts on the parent upload.
        conn.execute(
            "UPDATE payment_uploads SET "
            "  failed_count = (SELECT COUNT(*) FROM payment_lines "
            "                  WHERE upload_id=? "
            "                    AND (resolution_method IS NULL OR resolution_method='')) "
            "WHERE id=?",
            (line["upload_id"], line["upload_id"]),
        )
        conn.commit()
    return {"resolved": True, "method": body.method, "transaction_id": txn_id}
