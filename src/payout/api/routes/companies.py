"""Company config routes.

A company is a row in ``companies``. Three kinds exist (``payment_model``):

* ``payout_file`` — they send a payout file each cycle; the parser config
  (sheet, rider-id / payout / orders columns, optional COD hold) tells the
  engine how to read it. Rent is deducted from the payout, the rest released.
* ``per_order``   — no file. The office reads each rider's order count off the
  company's dashboard, the engine pays ``per_order_rate`` × orders through the
  same cycle (rent deducted the same way).
* ``direct``      — they pay riders themselves. Roster only; nothing to
  process, no cycles ever exist for them.

Admins create and edit companies here; nothing is ever deleted — a company
that stops is deactivated so its history stays readable.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException

from payout.api.auth import get_current_user, require_admin
from payout.api.schemas import CADENCES, PAYMENT_MODELS, CompanyIn, CompanyOut, CompanyPatch
from payout.db import get_connection
from payout.domain.activity import diff_fields, record_activity
from payout.domain.cycles import next_cycle_for
from payout.money import to_paise

router = APIRouter()

_COLS = (
    "company_name, parser_type, payout_sheet, rider_id_column, payout_column, "
    "orders_column, has_hold_sheet, hold_style, hold_sheet, hold_key_column, "
    "hold_amount_column, hold_status_column, is_active, rider_ids_shared_with, "
    "payment_model, cadence, per_order_rate, notes"
)
_EDITABLE = (
    "payment_model",
    "cadence",
    "per_order_rate",
    "notes",
    "rider_ids_shared_with",
    "is_active",
    "parser_type",
    "payout_sheet",
    "rider_id_column",
    "payout_column",
    "orders_column",
    "hold_style",
    "hold_sheet",
    "hold_key_column",
    "hold_amount_column",
    "hold_status_column",
)


def _out(r, counts: dict[str, tuple[int, int]] | None = None) -> CompanyOut:
    active, total = (counts or {}).get(r["company_name"], (0, 0))
    return CompanyOut(
        company_name=r["company_name"],
        parser_type=r["parser_type"],
        payout_column=r["payout_column"],
        has_hold_sheet=bool(r["has_hold_sheet"]),
        hold_style=r["hold_style"],
        is_active=bool(r["is_active"]),
        rider_ids_shared_with=r["rider_ids_shared_with"],
        payment_model=r["payment_model"] or "payout_file",
        cadence=r["cadence"] or "weekly",
        per_order_rate=r["per_order_rate"],
        notes=r["notes"],
        payout_sheet=r["payout_sheet"],
        rider_id_column=r["rider_id_column"],
        orders_column=r["orders_column"],
        hold_sheet=r["hold_sheet"],
        hold_key_column=r["hold_key_column"],
        hold_amount_column=r["hold_amount_column"],
        hold_status_column=r["hold_status_column"],
        active_riders=active,
        rider_ids=total,
    )


def _rider_counts(conn) -> dict[str, tuple[int, int]]:
    return {
        r["company"]: (int(r["active"] or 0), int(r["total"] or 0))
        for r in conn.execute(
            "SELECT company, SUM(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS active, "
            "COUNT(*) AS total FROM rider_master GROUP BY company"
        )
    }


def _validate(model: str | None, cadence: str | None, rate_paise: int | None) -> None:
    if model is not None and model not in PAYMENT_MODELS:
        raise HTTPException(400, f"payment_model must be one of {', '.join(PAYMENT_MODELS)}")
    if cadence is not None and cadence not in CADENCES:
        raise HTTPException(400, f"cadence must be one of {', '.join(CADENCES)}")
    if model == "per_order" and not rate_paise:
        raise HTTPException(400, "A per-order company needs a per-order rate (₹ per order).")
    if rate_paise is not None and rate_paise < 0:
        raise HTTPException(400, "per_order_rate cannot be negative")


@router.get("", response_model=list[CompanyOut])
def list_companies(_: dict = Depends(get_current_user)) -> list[CompanyOut]:
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT {_COLS} FROM companies ORDER BY is_active DESC, company_name"
        ).fetchall()
        counts = _rider_counts(conn)
    return [_out(r, counts) for r in rows]


@router.post("", response_model=CompanyOut, status_code=201)
def create_company(body: CompanyIn, user: dict = Depends(require_admin)) -> CompanyOut:
    name = body.company_name.strip()
    if not name:
        raise HTTPException(400, "company_name is required")
    with get_connection() as conn:
        if conn.execute(
            "SELECT 1 FROM companies WHERE LOWER(company_name)=LOWER(?)", (name,)
        ).fetchone():
            raise HTTPException(409, f"Company '{name}' already exists")
    rate = to_paise(body.per_order_rate) if body.per_order_rate is not None else None
    _validate(body.payment_model, body.cadence, rate)
    model = body.payment_model
    if model == "payout_file":
        if not (body.rider_id_column or "").strip() or not (body.payout_column or "").strip():
            raise HTTPException(
                400,
                "A payout-file company needs the rider-id column and the payout column "
                "as they appear in their file.",
            )
        parser_type = (body.parser_type or name.lower().replace(" ", "_").replace("'", "")).strip()
        rider_col, payout_col = body.rider_id_column.strip(), body.payout_column.strip()
    else:
        parser_type = "orders" if model == "per_order" else "none"
        rider_col, payout_col = "rider_id", "payout"
    hold_style = (body.hold_style or "").strip() or None
    if hold_style not in (None, "sheet", "column"):
        raise HTTPException(400, "hold_style must be 'sheet', 'column' or blank")
    shared = (body.rider_ids_shared_with or "").strip() or None
    with get_connection() as conn:
        if (
            shared
            and not conn.execute(
                "SELECT 1 FROM companies WHERE company_name=?", (shared,)
            ).fetchone()
        ):
            raise HTTPException(400, f"rider_ids_shared_with: unknown company '{shared}'")
        conn.execute(
            f"INSERT INTO companies ({_COLS}) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                name,
                parser_type,
                (body.payout_sheet or "").strip() or None,
                rider_col,
                payout_col,
                (body.orders_column or "").strip() or ("orders" if model == "per_order" else None),
                1 if hold_style else 0,
                hold_style,
                (body.hold_sheet or "").strip() or None,
                (body.hold_key_column or "").strip() or None,
                (body.hold_amount_column or "").strip() or None,
                (body.hold_status_column or "").strip() or None,
                1,
                shared,
                model,
                body.cadence,
                rate if model == "per_order" else None,
                (body.notes or "").strip() or None,
            ),
        )
        record_activity(
            conn,
            user,
            "company.create",
            entity_type="company",
            entity_id=name,
            label=name,
            details={"payment_model": model, "cadence": body.cadence, "per_order_rate": rate},
        )
        row = conn.execute(
            f"SELECT {_COLS} FROM companies WHERE company_name=?", (name,)
        ).fetchone()
        conn.commit()
    return _out(row)


@router.patch("/{company_name}", response_model=CompanyOut)
def update_company(
    company_name: str, body: CompanyPatch, user: dict = Depends(require_admin)
) -> CompanyOut:
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT {_COLS} FROM companies WHERE company_name=?", (company_name,)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"Unknown company '{company_name}'")
        before = dict(row)
        after = dict(before)
        given = body.model_dump(exclude_unset=True)
        for k, v in given.items():
            if k == "per_order_rate":
                after[k] = to_paise(v) if v is not None else None
            elif k == "is_active":
                after[k] = 1 if v else 0
            elif isinstance(v, str):
                after[k] = v.strip() or None
            else:
                after[k] = v
        model = after["payment_model"] or "payout_file"
        _validate(model, after["cadence"] or "weekly", after["per_order_rate"])
        if model == "payout_file" and not (after["rider_id_column"] and after["payout_column"]):
            raise HTTPException(
                400, "A payout-file company needs the rider-id column and the payout column."
            )
        if model != "payout_file":
            after["parser_type"] = "orders" if model == "per_order" else "none"
            after["rider_id_column"] = after["rider_id_column"] or "rider_id"
            after["payout_column"] = after["payout_column"] or "payout"
        if model != "per_order":
            after["per_order_rate"] = None
        if after["hold_style"] not in (None, "sheet", "column"):
            raise HTTPException(400, "hold_style must be 'sheet', 'column' or blank")
        after["has_hold_sheet"] = 1 if after["hold_style"] else 0
        shared = after["rider_ids_shared_with"]
        if shared:
            if shared == company_name:
                raise HTTPException(400, "A company cannot share rider ids with itself")
            if not conn.execute(
                "SELECT 1 FROM companies WHERE company_name=?", (shared,)
            ).fetchone():
                raise HTTPException(400, f"rider_ids_shared_with: unknown company '{shared}'")
        changed = diff_fields(before, after, (*_EDITABLE, "has_hold_sheet"))
        if changed:
            sets = ", ".join(f"{k}=?" for k in changed)
            conn.execute(
                f"UPDATE companies SET {sets} WHERE company_name=?",
                [after[k] for k in changed] + [company_name],
            )
            record_activity(
                conn,
                user,
                "company.update",
                entity_type="company",
                entity_id=company_name,
                label=company_name,
                details={"changed": changed},
            )
        row = conn.execute(
            f"SELECT {_COLS} FROM companies WHERE company_name=?", (company_name,)
        ).fetchone()
        counts = _rider_counts(conn)
        conn.commit()
    return _out(row, counts)


@router.get("/{company_name}/next-cycle")
def get_next_cycle(company_name: str, _: dict = Depends(get_current_user)) -> dict:
    """Return the next (cycle_start, cycle_end) for the given company.

    Reads MAX(cycle_end) from the transactions table for this company. If the
    company has no history yet, anchors on today using the company's cadence.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT cadence FROM companies WHERE company_name = ?", (company_name,)
        ).fetchone()
        if not row:
            raise HTTPException(404, f"Unknown company: {company_name!r}")
        latest = conn.execute(
            "SELECT MAX(cycle_end) AS last_end FROM transactions "
            "WHERE company = ? AND event_type IN ('PAYOUT','RENT','RENT_MISSED','RENT_RECOVERED','DUES_CARRY')",  # noqa: E501
            (company_name,),
        ).fetchone()
    last_end: date | None = None
    if latest and latest["last_end"]:
        try:
            last_end = date.fromisoformat(latest["last_end"])
        except ValueError:
            last_end = None
    start, end = next_cycle_for(company_name, last_end, row["cadence"])
    return {
        "company_name": company_name,
        "last_cycle_end": last_end.isoformat() if last_end else None,
        "cycle_start": start.isoformat(),
        "cycle_end": end.isoformat(),
    }
