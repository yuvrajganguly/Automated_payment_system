"""Per-provider tabs (Raft weekly, Blive monthly).

Three responsibilities per provider:

  GET  /providers/{provider}/period
      Aggregate ev_daily_ledger over a period, scoped to EVs of this provider.
      Returns per-EV breakdown — what we owe the provider, what we collected
      from riders, what's pending.

  POST /providers/{provider}/bills
      Upload a provider's bill Excel. Parses (EV ID, amount, status note).
      Stores in provider_bills + provider_bill_lines.

  GET  /providers/{provider}/bills
  GET  /providers/{provider}/bills/{bill_id}
      List past bills and drill into one. The detail tallies every line
      against ev_daily_ledger for the same period and surfaces discrepancies.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from io import BytesIO
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from payout.api.auth import get_current_user, require_admin
from payout.db import get_connection
from payout.domain.fleet_sync import IngestRow, ingest_master_rows
from payout.parsers.base import match_column

router = APIRouter()


def _normalize_provider(p: str) -> str:
    return (p or "").strip().title()


# ── Period aggregation ─────────────────────────────────────────────────────


@router.get("/{provider}/period")
def provider_period(
    provider: str,
    date_from: str,
    date_to: str,
    _: dict = Depends(get_current_user),
) -> dict:
    """Provider-scoped ledger aggregation between two dates (inclusive).

    Same shape as the old /raft/weekly endpoint, but filtered to one provider
    (Raft / Blive / …) and accepting an arbitrary date range so the caller
    decides weekly vs monthly bucketing.
    """
    prov = _normalize_provider(provider)
    try:
        d_from = date.fromisoformat(date_from)
        d_to   = date.fromisoformat(date_to)
    except ValueError:
        raise HTTPException(400, "date_from / date_to must be ISO dates.")
    if d_to < d_from:
        raise HTTPException(400, "date_to must be on or after date_from.")
    df_iso, dt_iso = d_from.isoformat(), d_to.isoformat()

    with get_connection() as conn:
        # Source of truth is ev_units → ev_models (the real fleet). The daily
        # ledger LEFT-joins on top so spare/idle EVs still appear in the list
        # with zeros, rather than silently disappearing whenever they had no
        # billable days in the picked window. Previously this query INNER
        # joined from ev_daily_ledger and the "EVs" card never matched the
        # Raft master since spare units were dropped.
        #
        # Status filter: exclude retired EVs only. 'spare' EVs are part of the
        # provider's active inventory (they're between riders, not gone).
        per_ev_rows = conn.execute(
            """
            SELECT u.ev_id, m.provider, m.model_name AS model, u.status,
                   COALESCE(SUM(l.provider_cost), 0) AS provider_owed,
                   COALESCE(SUM(l.daily_cost),    0) AS rider_expected,
                   COALESCE(SUM(CASE WHEN l.billing_status IN ('billed','recovered')
                                     THEN l.daily_cost ELSE 0 END), 0) AS rider_collected,
                   COALESCE(SUM(CASE WHEN l.billing_status='missed'
                                     THEN l.daily_cost ELSE 0 END), 0) AS rider_missed,
                   COALESCE(SUM(CASE WHEN l.billing_status='recovered'
                                     THEN l.daily_cost ELSE 0 END), 0) AS rider_recovered,
                   COALESCE(SUM(CASE WHEN l.billing_status='pending'
                                           OR (l.billing_status IS NULL AND l.state='billable')
                                     THEN l.daily_cost ELSE 0 END), 0) AS rider_pending,
                   COUNT(l.day) AS days,
                   GROUP_CONCAT(DISTINCT pr.display_name) AS holders
            FROM ev_units u
            JOIN ev_models m ON m.model_id = u.model_id
            LEFT JOIN ev_daily_ledger l
                   ON l.ev_id = u.ev_id AND l.day BETWEEN ? AND ?
            LEFT JOIN person_registry pr ON pr.person_id = l.assigned_person_id
            WHERE LOWER(m.provider) = LOWER(?)
              AND COALESCE(u.status, '') NOT IN ('retired', 'sold')
            GROUP BY u.ev_id, m.provider, m.model_name, u.status
            ORDER BY (COALESCE(SUM(l.daily_cost), 0) -
                      COALESCE(SUM(CASE WHEN l.billing_status IN ('billed','recovered')
                                        THEN l.daily_cost ELSE 0 END), 0)) DESC,
                     u.ev_id
            """,
            (df_iso, dt_iso, prov),
        ).fetchall()
        per_ev = [
            {
                "ev_id": r["ev_id"],
                "provider": r["provider"],
                "model": r["model"],
                "status": r["status"] or "spare",
                "holders": r["holders"] or "",
                "days": int(r["days"] or 0),
                "provider_owed":    round(float(r["provider_owed"] or 0), 2),
                "rider_expected":   round(float(r["rider_expected"] or 0), 2),
                "rider_collected":  round(float(r["rider_collected"] or 0), 2),
                "rider_missed":     round(float(r["rider_missed"] or 0), 2),
                "rider_recovered":  round(float(r["rider_recovered"] or 0), 2),
                "rider_pending":    round(float(r["rider_pending"] or 0), 2),
                "shortfall": round(
                    max(0.0, float(r["rider_expected"] or 0)
                            - float(r["rider_collected"] or 0)), 2),
            }
            for r in per_ev_rows
        ]
        active_count = sum(1 for e in per_ev if e["days"] > 0)
        idle_count   = sum(1 for e in per_ev if e["days"] == 0)
        totals = {
            "provider_owed":   round(sum(e["provider_owed"]    for e in per_ev), 2),
            "rider_expected":  round(sum(e["rider_expected"]   for e in per_ev), 2),
            "rider_collected": round(sum(e["rider_collected"]  for e in per_ev), 2),
            "rider_missed":    round(sum(e["rider_missed"]     for e in per_ev), 2),
            "rider_recovered": round(sum(e["rider_recovered"]  for e in per_ev), 2),
            "rider_pending":   round(sum(e["rider_pending"]    for e in per_ev), 2),
            "shortfall":       round(sum(e["shortfall"]        for e in per_ev), 2),
            "ev_count":        len(per_ev),       # total fleet for this provider
            "active_evs":      active_count,      # had ledger activity in window
            "idle_evs":        idle_count,        # in fleet but no activity
        }
        # Empty-state hint: if no EV models are registered for this provider
        # at all, the operator probably hasn't set up the rate card yet —
        # surface that distinctly from "fleet registered but no activity".
        if not per_ev:
            no_models = conn.execute(
                "SELECT 1 FROM ev_models WHERE LOWER(provider)=LOWER(?) LIMIT 1",
                (prov,),
            ).fetchone() is None
            totals["no_models_registered"] = no_models
    return {"provider": prov, "from": df_iso, "to": dt_iso,
            "totals": totals, "per_ev": per_ev}


# ── Bill upload + parsing ─────────────────────────────────────────────────


def _parse_bill_excel(file_bytes: bytes, file_name: str) -> list[dict]:
    """Parse a provider bill into a list of {ev_id, amount, status_note} dicts.

    Looks for an EV-id-ish column, an amount column, and a status-note column
    (heuristically the last text column). Tolerant of column-name variations
    so Raft and Blive can use slightly different headers.
    """
    name = (file_name or "").lower()
    try:
        if name.endswith(".csv") or name.endswith(".tsv"):
            sep = "\t" if name.endswith(".tsv") else ","
            df = pd.read_csv(BytesIO(file_bytes), sep=sep, dtype=str, keep_default_na=False)
        else:
            df = pd.read_excel(BytesIO(file_bytes), dtype=str)
    except Exception as exc:
        raise HTTPException(400, f"Couldn't open the file: {exc}")

    df.columns = [str(c).strip() for c in df.columns]
    ev_col     = match_column(df.columns, "ev_id", "ev id", "ev", "ev no",
                              "vehicle id", "vehicle no")
    amount_col = match_column(df.columns, "amount", "rent", "rent charged",
                              "weekly rent", "monthly rent", "total", "charge")
    # Status column heuristic: last non-empty text column.
    status_col = match_column(df.columns, "status", "remarks", "remark",
                              "notes", "comment", "comments")
    if not status_col and len(df.columns):
        # fall back: last column if it doesn't look numeric
        last_col = df.columns[-1]
        if not df[last_col].astype(str).str.replace(",", "").str.replace(".", "")\
                .str.replace("-", "").str.strip().str.match(r"^\d*$").all():
            status_col = last_col

    if not ev_col or not amount_col:
        raise HTTPException(
            400,
            f"Couldn't find required columns. Found {list(df.columns)}. "
            "Need at least an EV ID column and an amount column.",
        )

    def cell(row, col):
        if not col: return None
        v = row.get(col)
        if v is None or (isinstance(v, float) and pd.isna(v)): return None
        s = str(v).strip()
        return s if s and s.lower() != "nan" else None

    out: list[dict] = []
    line_no = 0
    for _, row in df.iterrows():
        ev_raw = cell(row, ev_col)
        amt = cell(row, amount_col)
        if not ev_raw and not amt:
            continue
        line_no += 1
        try:
            amount = float(str(amt).replace(",", "").replace("₹", "").strip()) if amt else 0.0
        except ValueError:
            amount = 0.0
        out.append({
            "line_no": line_no,
            "ev_id_raw": ev_raw,
            "ev_id": ev_raw,    # we don't yet have a normaliser; matching is exact
            "their_amount": amount,
            "status_note": cell(row, status_col) if status_col else None,
        })
    return out


@router.post("/{provider}/bills")
async def upload_bill(
    provider: str,
    period_start: str = Form(...),
    period_end:   str = Form(...),
    file: UploadFile = File(...),
    notes: Optional[str] = Form(None),
    user: dict = Depends(require_admin),
) -> dict:
    """Upload a provider bill and tally each line against our ledger."""
    prov = _normalize_provider(provider)
    try:
        d_from = date.fromisoformat(period_start)
        d_to   = date.fromisoformat(period_end)
    except ValueError:
        raise HTTPException(400, "period_start / period_end must be ISO dates.")
    if d_to < d_from:
        raise HTTPException(400, "period_end must be on or after period_start.")
    pdf_bytes = await file.read()
    lines = _parse_bill_excel(pdf_bytes, file.filename or "")
    if not lines:
        raise HTTPException(400, "No usable rows found in the file.")

    df_iso, dt_iso = d_from.isoformat(), d_to.isoformat()
    bill_total = round(sum(L["their_amount"] for L in lines), 2)

    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO provider_bills "
            "(provider, period_start, period_end, bill_total, line_count, "
            " file_name, uploaded_by, notes) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (prov, df_iso, dt_iso, bill_total, len(lines),
             file.filename, user["email"], notes),
        )
        bill_id = cur.lastrowid

        # Build a per-EV "our amount" map for tallying.
        our_amount_for_ev: dict[str, float] = {}
        for r in conn.execute(
            "SELECT l.ev_id, SUM(l.provider_cost) AS owed "
            "FROM ev_daily_ledger l "
            "JOIN ev_units  u ON u.ev_id=l.ev_id "
            "JOIN ev_models m ON m.model_id=u.model_id "
            "WHERE l.day BETWEEN ? AND ? AND LOWER(m.provider)=LOWER(?) "
            "GROUP BY l.ev_id",
            (df_iso, dt_iso, prov),
        ).fetchall():
            our_amount_for_ev[r["ev_id"]] = float(r["owed"] or 0)

        for L in lines:
            their = L["their_amount"]
            ours = our_amount_for_ev.get(L["ev_id"]) if L["ev_id"] else None
            disc = (their - ours) if ours is not None else None
            line_notes = None
            if L["ev_id"] not in our_amount_for_ev:
                line_notes = "EV not found in our ledger for this period"
            conn.execute(
                "INSERT INTO provider_bill_lines "
                "(bill_id, line_no, ev_id_raw, ev_id, their_amount, "
                " status_note, our_amount, discrepancy, notes) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (bill_id, L["line_no"], L["ev_id_raw"], L["ev_id"],
                 their, L["status_note"], ours,
                 round(disc, 2) if disc is not None else None, line_notes),
            )
        conn.commit()

    return {"bill_id": bill_id, "line_count": len(lines),
            "bill_total": bill_total}


@router.get("/{provider}/bills")
def list_bills(
    provider: str,
    _: dict = Depends(get_current_user),
) -> list[dict]:
    prov = _normalize_provider(provider)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, provider, period_start, period_end, bill_total, "
            "       line_count, file_name, uploaded_at, uploaded_by, notes "
            "FROM provider_bills WHERE LOWER(provider)=LOWER(?) "
            "ORDER BY uploaded_at DESC",
            (prov,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/{provider}/bills/{bill_id}")
def get_bill(
    provider: str, bill_id: int,
    _: dict = Depends(get_current_user),
) -> dict:
    prov = _normalize_provider(provider)
    with get_connection() as conn:
        bill = conn.execute(
            "SELECT * FROM provider_bills "
            "WHERE id=? AND LOWER(provider)=LOWER(?)",
            (bill_id, prov),
        ).fetchone()
        if not bill:
            raise HTTPException(404, "Bill not found")
        lines = conn.execute(
            "SELECT * FROM provider_bill_lines WHERE bill_id=? ORDER BY line_no",
            (bill_id,),
        ).fetchall()
    return {"bill": dict(bill), "lines": [dict(r) for r in lines]}


# ── Master inventory sync ─────────────────────────────────────────────────


def _parse_master_excel(file_bytes: bytes, file_name: str) -> list[IngestRow]:
    """Parse a provider's EV master into IngestRow entries.

    Looks for an EV-id column and a model column under flexible header
    aliases (Raft's master uses "Tracker  No" and "Model"; Blive may
    differ). Other columns are ignored — assignments live elsewhere
    and the master is treated as inventory truth, not assignment truth.
    """
    name = (file_name or "").lower()
    try:
        if name.endswith(".csv") or name.endswith(".tsv"):
            sep = "\t" if name.endswith(".tsv") else ","
            df = pd.read_csv(BytesIO(file_bytes), sep=sep, dtype=str, keep_default_na=False)
        else:
            df = pd.read_excel(BytesIO(file_bytes), dtype=str)
    except Exception as exc:
        raise HTTPException(400, f"Couldn't open the file: {exc}")

    df.columns = [str(c).strip() for c in df.columns]
    ev_col = match_column(df.columns, "ev_id", "ev id", "ev", "ev no",
                          "tracker no", "tracker  no", "tracker",
                          "vehicle id", "vehicle no")
    model_col = match_column(df.columns, "model", "ev model", "vehicle model")
    if not ev_col or not model_col:
        raise HTTPException(
            400,
            f"Couldn't find required columns. Found {list(df.columns)}. "
            "Need at least an EV-id column (e.g. 'Tracker No') and a model column.",
        )

    def cell(row, col):
        v = row.get(col)
        if v is None or (isinstance(v, float) and pd.isna(v)): return None
        s = str(v).strip()
        return s if s and s.lower() != "nan" else None

    out: list[IngestRow] = []
    for _, row in df.iterrows():
        ev_id = cell(row, ev_col)
        model = cell(row, model_col)
        if not ev_id and not model:
            continue
        out.append(IngestRow(ev_id=ev_id or "", model_name=model))
    return out


@router.post("/{provider}/master")
async def sync_master(
    provider: str,
    file: UploadFile = File(...),
    _: dict = Depends(require_admin),
) -> dict:
    """Sync a provider's fleet from their master Excel.

    Doesn't delete EVs missing from the master (that would be destructive
    when the master is being uploaded in pieces). Returns a summary the
    UI can show: units added/updated, models auto-created, and any
    models whose rate was set to the fallback and needs an operator to
    review it.
    """
    prov = _normalize_provider(provider)
    file_bytes = await file.read()
    rows = _parse_master_excel(file_bytes, file.filename or "")
    if not rows:
        raise HTTPException(400, "No usable rows found in the master.")

    with get_connection() as conn:
        report = ingest_master_rows(conn, prov, rows)
        conn.commit()
    return {"provider": prov, "rows_seen": len(rows), **report.as_dict()}


@router.delete("/{provider}/bills/{bill_id}")
def delete_bill(
    provider: str, bill_id: int,
    _: dict = Depends(require_admin),
) -> dict:
    prov = _normalize_provider(provider)
    with get_connection() as conn:
        n = conn.execute(
            "DELETE FROM provider_bill_lines WHERE bill_id=?", (bill_id,),
        ).rowcount
        c = conn.execute(
            "DELETE FROM provider_bills "
            "WHERE id=? AND LOWER(provider)=LOWER(?)",
            (bill_id, prov),
        ).rowcount
        conn.commit()
    return {"deleted_bill": c, "deleted_lines": n}
