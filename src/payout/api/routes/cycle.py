"""Cycle routes: upload a company file, preview or commit, get the xlsx output."""

from __future__ import annotations

import base64
import dataclasses
import io
import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from payout.api.auth import require_admin
from payout.api.schemas import RiderOverrideIn
from payout.db import get_connection
from payout.domain.engine import (
    CycleAlreadyCommitted,
    CycleOverrides,
    RiderOverride,
    process_cycle,
)
from payout.money import to_paise
from payout.output import build_output, build_output_filename

router = APIRouter()


def _json_safe(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(x) for x in value]
    return value


def _serialize(result) -> dict:
    return _json_safe(dataclasses.asdict(result))


def _parse_overrides(raw: str | None) -> CycleOverrides:
    """Accepts a JSON string: {"per_rider": [...], "adjustments": [...]}."""
    if not raw:
        return CycleOverrides()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid overrides JSON: {exc.msg}",
        ) from exc

    per_rider: dict[str, RiderOverride] = {}
    for item in data.get("per_rider", []) or []:
        ov = RiderOverrideIn.model_validate(item)
        per_rider[ov.rider_id] = RiderOverride(
            waive_days=ov.waive_days,
            waive_all=ov.waive_all,
            rent_override=(to_paise(ov.rent_override) if ov.rent_override is not None else None),
            force_hold=ov.force_hold,
            force_release=ov.force_release,
        )
    return CycleOverrides(per_rider=per_rider, adjustments=data.get("adjustments", []) or [])


def _store_rates(conn, company: str) -> dict[str, dict]:
    """rider_id → the store-level pay figures for that rider's hub (paise),
    only the fields the store overrides (Admin → Hubs)."""
    rows = conn.execute(
        "SELECT rm.rider_id, ch.per_order_rate, ch.salary, ch.incentive_per_order, "
        "       ch.incentive_per_day "
        "FROM rider_master rm JOIN company_hubs ch ON ch.company=rm.company AND ch.hub=rm.hub "
        "WHERE rm.company=?",
        (company,),
    ).fetchall()
    return {
        r["rider_id"]: {k: v for k, v in dict(r).items() if k != "rider_id" and v is not None}
        for r in rows
    }


def _orders_to_parse_result(conn, company: str, raw: str | None, rate_paise: int | None):
    """Turn the typed order counts into the records a payout file would give.

    Payout = orders × rate in paise, exactly what a parsed file yields. The
    rate is the rider's store's when the store has one (Admin → Hubs), else
    the company's. A rider listed twice is summed; zero-order riders are kept
    so the cycle treats them as present (no rent missed for being absent)."""
    from payout.domain.models import ParseResult, RiderRecord

    store = _store_rates(conn, company)
    if not rate_paise and not any("per_order_rate" in v for v in store.values()):
        raise HTTPException(400, f"{company} has no per-order rate set (Admin → Companies).")
    if not raw:
        raise HTTPException(400, f"{company} is paid per order — enter the order counts.")
    try:
        items = json.loads(raw)
        assert isinstance(items, list)
    except (ValueError, AssertionError) as exc:
        raise HTTPException(400, "orders must be a JSON list of {rider_id, orders}") from exc
    counts: dict[str, float] = {}
    for it in items:
        rid = str((it or {}).get("rider_id", "")).strip()
        if not rid:
            continue
        try:
            n = float(it.get("orders") or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"orders for {rid} is not a number") from exc
        if n < 0:
            raise HTTPException(400, f"orders for {rid} cannot be negative")
        counts[rid] = counts.get(rid, 0.0) + n
    if not counts:
        raise HTTPException(400, "No riders with order counts were given.")
    # Parsed records carry paise (the parsers call to_paise); do the same.
    records = []
    for rid, n in counts.items():
        rate_for = store.get(rid, {}).get("per_order_rate") or rate_paise
        if not rate_for:
            raise HTTPException(
                400, f"{rid} has no per-order rate — set one for its store or the company."
            )
        records.append(RiderRecord(rider_id=rid, payout=int(round(n * rate_for)), orders=n))
    rate = (rate_paise or 0) / 100.0
    return ParseResult(
        company=company,
        records=records,
        sheet="orders entered by hand",
        matched_columns={
            "rider_id": "rider_id",
            "payout": f"orders × ₹{rate:g}" + (" (store rates where set)" if store else ""),
            "orders": "orders",
        },
        warnings=[],
    )


def _salary_to_parse_result(conn, company: str, raw: str | None, co) -> tuple[object, list[dict]]:
    """Salaried company: the office marks days present and orders per rider.

    Per rider (salary from the rider row, paise per cycle):
        days_off   = max(0, expected_days − days_present)
        base_pay   = salary − days_off × salary / expected_days
        incentives = orders × incentive_per_order + days_present × incentive_per_day
        payout     = base_pay + incentives
    Returns the ParseResult for the engine and the working per rider."""
    from payout.domain.models import ParseResult, RiderRecord

    if not raw:
        raise HTTPException(400, f"{company} is salaried — mark days present and orders.")
    try:
        items = json.loads(raw)
        assert isinstance(items, list)
    except (ValueError, AssertionError) as exc:
        raise HTTPException(
            400, "attendance must be a JSON list of {rider_id, days_present, orders}"
        ) from exc
    expected = int(co["salary_expected_days"] or 26)
    co_inc_order = int(co["incentive_per_order"] or 0)
    co_inc_day = int(co["incentive_per_day"] or 0)
    store = _store_rates(conn, company)
    salaries = {
        r["rider_id"]: (int(r["salary"] or 0), r["person_id"], r["name"])
        for r in conn.execute(
            "SELECT rider_id, salary, person_id, name FROM rider_master WHERE company=?",
            (company,),
        )
    }
    seen: dict[str, dict] = {}
    for it in items:
        rid = str((it or {}).get("rider_id", "")).strip()
        if not rid:
            continue
        try:
            present = float(it.get("days_present") or 0)
            n_orders = float(it.get("orders") or 0)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, f"days/orders for {rid} are not numbers") from exc
        if present < 0 or n_orders < 0:
            raise HTTPException(400, f"days/orders for {rid} cannot be negative")
        if present > 31:
            raise HTTPException(400, f"days present for {rid} cannot exceed 31")
        if rid in seen:
            seen[rid]["days_present"] += present
            seen[rid]["orders"] += n_orders
        else:
            seen[rid] = {"rider_id": rid, "days_present": present, "orders": n_orders}
    if not seen:
        raise HTTPException(400, "No riders were marked.")
    records, lines = [], []
    for rid, it in seen.items():
        salary, pid, name = salaries.get(rid, (0, None, None))
        st = store.get(rid, {})
        # Rider's own salary first, then the store's default (Admin → Hubs).
        salary = salary or int(st.get("salary") or 0)
        inc_order = int(st.get("incentive_per_order", co_inc_order))
        inc_day = int(st.get("incentive_per_day", co_inc_day))
        if rid in salaries and not salary:
            raise HTTPException(
                400,
                f"{name or rid} has no salary set — enter it in the table, or set a "
                "default for their store under Admin → Hubs.",
            )
        days_off = max(0.0, expected - it["days_present"])
        base = int(round(salary - days_off * salary / expected))
        base = max(0, base)
        incentives = int(round(it["orders"] * inc_order + it["days_present"] * inc_day))
        payout = base + incentives
        records.append(RiderRecord(rider_id=rid, payout=payout, orders=it["orders"]))
        lines.append(
            {
                "rider_id": rid,
                "person_id": pid,
                "name": name,
                "days_present": it["days_present"],
                "days_off": days_off,
                "orders": it["orders"],
                "salary": salary,
                "base_pay": base,
                "incentives": incentives,
                "payout": payout,
            }
        )
    parsed = ParseResult(
        company=company,
        records=records,
        sheet="attendance marked by hand",
        matched_columns={
            "rider_id": "rider_id",
            "payout": "salary − days off + incentives",
            "orders": "orders",
        },
        warnings=[],
    )
    return parsed, lines


def _record_salary_inputs(company, cycle_start, cycle_end, lines, user) -> None:
    """Keep what was marked for the cycle (after a successful commit)."""
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM salary_inputs WHERE company=? AND cycle_start=? AND cycle_end=?",
            (company, cycle_start.isoformat(), cycle_end.isoformat()),
        )
        for ln in lines:
            conn.execute(
                "INSERT INTO salary_inputs (company, cycle_start, cycle_end, rider_id, "
                " person_id, days_present, orders, salary, base_pay, incentives, payout, "
                " created_by) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    company,
                    cycle_start.isoformat(),
                    cycle_end.isoformat(),
                    ln["rider_id"],
                    ln["person_id"],
                    ln["days_present"],
                    ln["orders"],
                    ln["salary"],
                    ln["base_pay"],
                    ln["incentives"],
                    ln["payout"],
                    user["email"],
                ),
            )
        conn.commit()


_SHEET_ID_ALIASES = ("rider_id", "rider id", "id", "worker code", "rider", "fe id", "employee id")
_SHEET_DAYS_ALIASES = (
    "days_present",
    "days present",
    "present",
    "attendance",
    "days",
    "present days",
)
_SHEET_ORDERS_ALIASES = ("orders", "orders delivered", "delivered", "deliveries", "total orders")
_SHEET_NAME_ALIASES = ("name", "rider name", "rider_name")


@router.post("/parse-sheet")
async def parse_attendance_sheet(
    company: str = Form(...),
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    _: dict = Depends(require_admin),
) -> dict:
    """Read an attendance / orders sheet the office keeps (xlsx or csv) into
    rows the Process Payout table can take: {rider_id, name, days_present,
    orders}. Column headers are matched loosely; unmatched rider ids are
    reported so the operator can fix the sheet rather than lose rows.

    For a company on the pincode ratecard (Shadowfax) it takes ``files`` — the
    daily Vendor_data downloads — and answers what they hold: each file's
    date and rows, which file each order date came from, and the cycle dates
    to suggest (earliest..latest order date, after the last committed cycle).
    """
    import pandas as pd

    from payout.parsers.base import match_column

    uploads = [f for f in (files or []) if f is not None] + ([file] if file is not None else [])
    with get_connection() as conn:
        co = conn.execute(
            "SELECT rate_model FROM companies WHERE company_name=?", (company,)
        ).fetchone()
        last = conn.execute(
            "SELECT MAX(cycle_end) AS e FROM company_cycles WHERE company=?", (company,)
        ).fetchone()
    if co and co["rate_model"] == "pincode_ratecard":
        from payout.domain import shadowfax

        if not uploads:
            raise HTTPException(400, "No files")
        try:
            batch = shadowfax.read_files(
                [(u.filename or "file.xlsx", await u.read()) for u in uploads]
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        start, end = shadowfax.suggest_cycle(
            batch, str(last["e"])[:10] if last and last["e"] else None
        )
        return {
            "kind": "shadowfax",
            "files": [f.__dict__ for f in batch.files],
            "order_dates": sorted(
                ({"order_date": od, "source_file": src} for od, src in batch.date_source.items()),
                key=lambda x: x["order_date"],
            ),
            "riders_count": len({k[0] for k in batch.rows}),
            "ztp_count": len(batch.ztp),
            "suggested_cycle_start": start,
            "suggested_cycle_end": end,
            "last_cycle_end": str(last["e"])[:10] if last and last["e"] else None,
        }
    if not uploads:
        raise HTTPException(400, "No file")
    file = uploads[0]
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty file")
    try:
        if (file.filename or "").lower().endswith(".csv"):
            df = pd.read_csv(io.BytesIO(raw))
        else:
            df = pd.read_excel(io.BytesIO(raw))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Could not read the sheet: {exc}") from exc
    df.columns = [str(c).strip() for c in df.columns]
    id_col = match_column(df.columns, *_SHEET_ID_ALIASES)
    if not id_col:
        raise HTTPException(
            400, "No rider-id column found (expected a header like 'Rider ID' or 'ID')."
        )
    days_col = match_column(df.columns, *_SHEET_DAYS_ALIASES)
    orders_col = match_column(df.columns, *_SHEET_ORDERS_ALIASES)
    name_col = match_column(df.columns, *_SHEET_NAME_ALIASES)
    with get_connection() as conn:
        known = {
            r["rider_id"]: r["name"]
            for r in conn.execute(
                "SELECT rider_id, name FROM rider_master WHERE company=? AND is_active=1",
                (company,),
            )
        }

    def num(rec, col):
        if not col:
            return None
        try:
            f = float(rec.get(col))
        except (TypeError, ValueError):
            return None
        return None if f != f else f  # NaN

    rows, unknown = [], []
    for _, r in df.iterrows():
        rid = str(r.get(id_col, "") or "").strip()
        if rid.endswith(".0") and rid[:-2].isdigit():
            rid = rid[:-2]
        if not rid or rid.lower() == "nan":
            continue
        nm = str(r.get(name_col) or "").strip() if name_col else ""
        row = {
            "rider_id": rid,
            "name": (nm if nm and nm.lower() != "nan" else "") or known.get(rid),
            "days_present": num(r, days_col),
            "orders": num(r, orders_col),
        }
        (rows if rid in known else unknown).append(row)
    return {
        "rows": rows,
        "unknown": unknown,
        "matched": {"rider_id": id_col, "days_present": days_col, "orders": orders_col},
    }


@router.post("/run")
async def run_cycle(
    company: str = Form(...),
    cycle_start: date | None = Form(None),
    cycle_end: date | None = Form(None),
    commit: bool = Form(False),
    force: bool = Form(False),
    ad_hoc: bool = Form(False),
    label: str | None = Form(None),
    overrides: str | None = Form(None),
    orders: str | None = Form(None),
    attendance: str | None = Form(None),
    file: UploadFile | None = File(None),
    files: list[UploadFile] | None = File(None),
    ztp_apply: str | None = Form(None),
    user: dict = Depends(require_admin),
) -> dict:
    """Process a company cycle.

    A per-order company on the pincode ratecard (Shadowfax) sends ``files`` —
    every daily Vendor_data download for the cycle, in one go — instead of
    typed counts; see domain/shadowfax.py. ``ztp_apply`` is a JSON list of
    rider ids whose Shadowfax ZTP penalties should be passed on (off unless
    listed).

    Payout-file companies send `file` (their .xlsx). Per-order companies send
    `orders` instead — a JSON list of {"rider_id", "orders"} typed off the
    company's dashboard; the payout is orders × the company's per-order rate.
    Direct-pay companies have nothing to process and are refused.

    - `commit=false` (default) runs as a dry-run preview; nothing is written.
    - `commit=true` writes everything atomically AND returns the styled .xlsx as
      base64 in the response so the frontend can trigger a download.
    - `ad_hoc=true` pays a surge file that is not a cycle: no rent, no meter,
      no absence pass, no cycle row. The dates are optional and default to
      today, because there is no window to state — see engine.process_cycle.
    """
    if ad_hoc:
        # "It does not even need a time window — just process what we
        # received." The ledger still needs a date on every row, so both ends
        # collapse to the day it is processed.
        today = date.today()
        cycle_start = cycle_start or today
        cycle_end = cycle_end or cycle_start
    if cycle_start is None or cycle_end is None:
        raise HTTPException(400, "A cycle needs a start and an end date.")
    if cycle_end < cycle_start:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cycle_end must be on or after cycle_start",
        )
    # Guard: a cycle whose end is meaningfully in the future would write
    # 'billed' day-rows for days that haven't happened yet. If a return or
    # maintenance fires between now and cycle_end those rows go stale. Allow
    # a 3-day grace so timezone / "the file just landed at 11:59pm" cases
    # work, but refuse anything farther out.
    from datetime import date as _date_cls
    from datetime import timedelta as _td

    today = _date_cls.today()
    if cycle_end > today + _td(days=3):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"cycle_end ({cycle_end}) is more than 3 days in the future. "
                "Future-dated cycles write daily-ledger rows for days that "
                "haven't happened — returns or maintenance after today would "
                "leave the ledger stale. Wait until the cycle's actually closed."
            ),
        )
    with get_connection() as conn:
        co = conn.execute(
            "SELECT payment_model, per_order_rate, is_active, salary_expected_days, "
            " incentive_per_order, incentive_per_day, parser_type, rate_model "
            "FROM companies WHERE company_name=?",
            (company,),
        ).fetchone()
        if not co or not co["is_active"]:
            raise HTTPException(400, f"Company '{company}' not found or not active.")
        model = co["payment_model"] or "payout_file"
        salary_lines: list[dict] = []
        if model == "salary":
            parsed, salary_lines = _salary_to_parse_result(conn, company, attendance, co)
    file_bytes: bytes | None = None
    if model != "salary":
        parsed = None
    if model == "direct":
        raise HTTPException(
            400,
            f"{company} pays its riders directly — there is no payout to process. "
            "Change how it pays under Admin → Companies if that is wrong.",
        )
    sfx = None
    if model == "per_order" and co["rate_model"] == "pincode_ratecard" and not orders:
        from payout.domain import shadowfax

        uploads = [f for f in (files or []) if f is not None] + ([file] if file is not None else [])
        if not uploads:
            raise HTTPException(
                400,
                f"{company} is paid per order — drop the Vendor_data files for this cycle, "
                "or enter the order counts.",
            )
        blobs = [(u.filename or "file.xlsx", await u.read()) for u in uploads]
        try:
            batch = shadowfax.read_files(blobs)
            with get_connection() as conn:
                sfx = shadowfax.price(
                    conn, company, batch, cycle_start, cycle_end, fallback_rate=co["per_order_rate"]
                )
            sfx._files = batch.files  # type: ignore[attr-defined]  # for the preview
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if not sfx.records:
            raise HTTPException(
                400,
                "No orders to pay in these files for this cycle"
                + (" — every day in it was already paid." if sfx.already_paid else "."),
            )
        parsed = shadowfax.to_parse_result(company, sfx)
    elif model == "per_order":
        with get_connection() as conn:
            parsed = _orders_to_parse_result(conn, company, orders, co["per_order_rate"])
    elif model == "salary":
        pass
    else:
        if file is None:
            raise HTTPException(400, f"{company} sends a payout file — upload it to process.")
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty file upload")

    cycle_overrides = _parse_overrides(overrides)
    if sfx is not None:
        _shadowfax_overrides(company, sfx, cycle_overrides, ztp_apply)
    try:
        result = process_cycle(
            company=company,
            cycle_start=cycle_start,
            cycle_end=cycle_end,
            file_bytes=file_bytes,
            parsed=parsed,
            overrides=cycle_overrides,
            created_by=user["email"],
            commit=commit,
            force=force,
            ad_hoc=ad_hoc,
            label=label,
            before_commit=(
                (lambda c: _record_days(c, company, cycle_start, cycle_end, sfx))
                if sfx is not None
                else None
            ),
        )
    except CycleAlreadyCommitted as exc:
        # Guard lives in the engine's transaction now (was a racy pre-check here).
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if file_bytes is not None and co["parser_type"] == "house":
        # The office's own sheet carries a Rent charged and a Net payout column.
        # They are checked against what the engine computed, never used: the
        # ledger's rent comes from the vehicle's days, and a difference is
        # something the operator should see before committing.
        from payout.parsers import parse_file
        from payout.parsers.house import check_sheet_against_engine

        try:
            sheet = parse_file(company, file_bytes)
            result.warnings.extend(
                check_sheet_against_engine(sheet.records, result.pay_rows + result.dues_rows)
            )
        except ValueError:
            pass  # the engine already reported the parse failure

    if sfx is not None:
        _shadowfax_after_run(company, cycle_start, cycle_end, sfx, result, commit)

    response: dict = {"result": _serialize(result)}
    if sfx is not None:
        response["shadowfax"] = _shadowfax_payload(sfx, result)
    if salary_lines:
        response["salary_lines"] = salary_lines
        if commit and result.committed:
            _record_salary_inputs(company, cycle_start, cycle_end, salary_lines, user)
    if commit:
        buf = build_output(result)
        if sfx is not None:
            buf = _shadowfax_sheets(buf, sfx)
        response["xlsx"] = {
            "filename": build_output_filename(company, cycle_start, cycle_end),
            "content_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
            "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        }
    return response


# ── Shadowfax (per-order on the pincode ratecard) ───────────────────────────


def _shadowfax_overrides(company, sfx, ov, ztp_apply: str | None) -> None:
    """Riders with no bank account are held (their net stays a balance, not
    released) unless the operator forced a release; ZTP penalties listed in
    ``ztp_apply`` become ADJUSTMENT rows with the AWBs in the reason."""
    from payout.domain.engine import RiderOverride

    with get_connection() as conn:
        rids = [r.rider_id for r in sfx.records]
        if rids:
            marks = ",".join("?" * len(rids))
            for r in conn.execute(
                f"SELECT rider_id FROM rider_master WHERE company=? AND rider_id IN ({marks}) "
                "AND COALESCE(TRIM(account_no), '') = ''",
                (company, *rids),
            ).fetchall():
                cur = ov.per_rider.get(r["rider_id"]) or RiderOverride()
                if not cur.force_release:
                    cur.force_hold = True
                ov.per_rider[r["rider_id"]] = cur
                for x in sfx.riders:
                    if x["rider_id"] == r["rider_id"]:
                        x["bank"] = "missing — held"
    try:
        chosen = set(json.loads(ztp_apply)) if ztp_apply else set()
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "ztp_apply must be a JSON list of rider ids") from exc
    for rid in chosen:
        rows = [z for z in sfx.ztp if z["rider_id"] == str(rid)]
        total = sum(z["penalty"] for z in rows)
        if total > 0:
            ov.adjustments.append(
                {
                    "rider_id": str(rid),
                    "amount": -total,
                    "reason": "Shadowfax ZTP penalty — AWB "
                    + ", ".join(z["awb_number"] for z in rows),
                }
            )


def _record_days(conn, company, cycle_start, cycle_end, sfx) -> None:
    from payout.domain import shadowfax

    shadowfax.record_paid_days(conn, company, cycle_start, cycle_end, sfx.day_rows)


def _shadowfax_after_run(company, cycle_start, cycle_end, sfx, result, commit: bool) -> None:
    """Map Shadowfax hubs onto ours for the onboarding list and the preview —
    display only; rider_master.hub is never written from the file."""
    from payout.domain import shadowfax

    with get_connection() as conn:
        ours = {
            shadowfax.norm_hub(r["hub"]): r["hub"]
            for r in conn.execute(
                "SELECT DISTINCT hub FROM rider_master WHERE company=? AND hub IS NOT NULL",
                (company,),
            ).fetchall()
        }
        by_rid = {r["rider_id"]: r for r in sfx.riders}
        for u in result.unknown_riders:
            src = by_rid.get(str(u.get("rider_id")))
            if src:
                u["hub"] = ours.get(shadowfax.norm_hub(src["file_hub"]), "") or u.get("hub", "")
                u["gross"] = src["gross"]
                u["orders"] = src["orders"]
        for x in sfx.riders:
            x["hub"] = ours.get(shadowfax.norm_hub(x["file_hub"]), "")
            x.setdefault("bank", "ok")


def _shadowfax_payload(sfx, result) -> dict:
    rows = {r.rider_id: r for r in result.pay_rows + result.dues_rows}
    riders = []
    for x in sfx.riders:
        r = rows.get(x["rider_id"])
        riders.append(
            {
                **x,
                "rent": getattr(r, "rent", 0) if r else 0,
                "released": getattr(r, "released", 0) if r else 0,
                "known": r is not None,
            }
        )
    return {
        "files": [f.__dict__ for f in sorted(sfx_files(sfx), key=lambda f: f.file_date)],
        "order_dates": sfx.order_dates,
        "riders": riders,
        "already_paid": sfx.already_paid,
        "revised_after_payment": sfx.revised,
        "ztp": sfx.ztp,
        "totals": sfx.totals,
        "ratecard_used": sfx.ratecard_used,
    }


def sfx_files(sfx):
    return getattr(sfx, "_files", [])


def _shadowfax_sheets(buf, sfx):
    """Two sheets on the standard workbook: every rider × day × pincode line
    with the rates used, and the part of the ratecard that was used."""
    import io as _io

    from openpyxl import load_workbook

    from payout.exports import add_styled_sheet

    wb = load_workbook(buf)
    add_styled_sheet(
        wb,
        sheet_name="Shadowfax detail",
        headers=(
            "Rider ID",
            "Name",
            "Order date",
            "Pincode",
            "Cluster",
            "PPD",
            "COD",
            "RVP",
            "SDD",
            "Club",
            "FM",
            "RTS",
            "Orders",
            "PPD rate",
            "COD rate",
            "RVP rate",
            "SDD rate",
            "Club rate",
            "Rider pay",
            "Shadowfax payout",
            "Margin",
            "Flags",
            "From file",
        ),
        rows=[
            (
                d["rider_id"],
                d["name"],
                d["order_date"],
                d["pincode"],
                d["cluster"],
                d["ppd_orders"],
                d["cod_orders"],
                d["rvp_orders"],
                d["sdd_orders"],
                d["club_orders"],
                d["fm_orders"],
                d["rts_orders"],
                d["orders"],
                d["rate_ppd"],
                d["rate_cod"],
                d["rate_rvp"],
                d["rate_sdd"],
                d["rate_club"],
                d["rider_pay"],
                d["sfx_payout"],
                d["margin"],
                "; ".join(d["flags"]),
                d["source_file"],
            )
            for d in sfx.detail
        ],
        numeric_cols=tuple(range(6, 22)),
        totals_cols=(6, 7, 8, 9, 10, 11, 12, 13, 19, 20, 21),
        money_cols=(14, 15, 16, 17, 18, 19, 20, 21),
        left_align_cols=(1, 2, 3, 4, 5, 22, 23),
    )
    add_styled_sheet(
        wb,
        sheet_name="Ratecard used",
        headers=("Pincode", "Cluster", "Effective from", "PPD", "COD", "RVP", "SDD", "Club"),
        rows=[
            (
                r["pincode"],
                r["cluster"],
                r["effective_from"],
                r["rate_ppd"],
                r["rate_cod"],
                r["rate_rvp"],
                r["rate_sdd"],
                r["rate_club"],
            )
            for r in sfx.ratecard_used
        ],
        numeric_cols=(4, 5, 6, 7, 8),
        money_cols=(4, 5, 6, 7, 8),
        left_align_cols=(1, 2, 3),
    )
    out = _io.BytesIO()
    wb.save(out)
    out.seek(0)
    return out
