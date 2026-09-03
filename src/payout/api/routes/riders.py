"""Rider routes: list, create, bulk-upload, fetch one."""

from __future__ import annotations

from io import BytesIO

import pandas as pd
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile

from payout.api.auth import get_current_user, require_admin
from payout.api.schemas import ExportSelection, RenameRiderIdIn, RiderIn, RiderOut, RiderPatch
from payout.db import get_connection
from payout.exports import xlsx_response
from payout.ingest.importer import _init_person
from payout.parsers.base import match_column

router = APIRouter()


def _rider_dict(row) -> dict:
    d = dict(row)
    d["is_active"] = bool(d["is_active"])
    return d


def _next_placeholder_rider_id(conn, company: str) -> str:
    """Generate a unique placeholder rider_id for riders whose company-issued
    ID hasn't been assigned yet. Format: ``QSPEND<NNNN>`` scoped per company."""
    row = conn.execute(
        "SELECT rider_id FROM rider_master "
        "WHERE company=? AND rider_id LIKE 'QSPEND%' "
        "ORDER BY rider_id DESC LIMIT 1",
        (company,),
    ).fetchone()
    n = 1
    if row:
        try:
            n = int(row["rider_id"].replace("QSPEND", "")) + 1
        except ValueError:
            n = 1
    return f"QSPEND{n:04d}"


def _find_existing_rider(
    conn, name: str, company: str, account_no: str | None = None
) -> dict | None:
    """Return an existing rider_master row when this rider already exists by
    (name, company) — case-insensitive — or by (account_no, company) when an
    account_no is provided."""
    row = conn.execute(
        "SELECT rider_id, company, person_id, name FROM rider_master "
        "WHERE company=? AND LOWER(name)=LOWER(?) LIMIT 1",
        (company, name),
    ).fetchone()
    if row:
        return dict(row)
    if account_no and str(account_no).strip():
        row = conn.execute(
            "SELECT rider_id, company, person_id, name FROM rider_master "
            "WHERE company=? AND account_no=? AND account_no <> '' LIMIT 1",
            (company, str(account_no).strip()),
        ).fetchone()
        if row:
            return dict(row)
    return None


def _account_owner_elsewhere(conn, account_no, person_id):
    """If ``account_no`` is already on file at any rider_master row for a
    *different* person_id, return that conflicting row. Otherwise None.

    Empty / null account_no never conflicts. Comparison ignores surrounding
    whitespace; we don't normalise leading zeros etc. because banks vary.
    Pass ``person_id=None`` when creating a brand-new person — any existing
    holder of the account is then a conflict.
    """
    if not account_no or not str(account_no).strip():
        return None
    acct = str(account_no).strip()
    rows = conn.execute(
        "SELECT rider_id, company, person_id, name "
        "FROM rider_master WHERE account_no = ? AND account_no <> ''",
        (acct,),
    ).fetchall()
    for r in rows:
        if person_id is None or r["person_id"] != person_id:
            return dict(r)
    return None


def _conflict_message(conflict: dict, action: str = "save") -> str:
    return (
        f"That account number is already on file for "
        f"person_id={conflict['person_id']} ({conflict['name'] or 'unknown'}, "
        f"rider_id={conflict['rider_id']} @ {conflict['company']}). "
        f"Cannot {action} the same account against a different person. "
        f"Use 'Link riders' if this is actually the same person across companies."
    )


def _insert_rider_into_db(
    conn, *, rider_id, company, name, hub, vehicle, account_no, ifsc, person_id=None
):
    """Shared write path used by both POST and bulk import.
    Returns (created: bool, rider_id: str, person_id: int).
    Raises HTTPException(400) on unknown company; HTTPException(409) on
    (rider_id, company) PK collision.

    When ``person_id`` is supplied the new rider_master row is attached to that
    existing person directly (skipping the display_name lookup) — used when
    adding a person to a second company."""
    if not conn.execute("SELECT 1 FROM companies WHERE company_name=?", (company,)).fetchone():
        raise HTTPException(400, f"Unknown company {company!r}")
    if not rider_id:
        rider_id = _next_placeholder_rider_id(conn, company)
    if conn.execute(
        "SELECT 1 FROM rider_master WHERE rider_id=? AND company=?",
        (rider_id, company),
    ).fetchone():
        raise HTTPException(409, f"Rider {rider_id} already exists for {company}")
    if person_id is not None:
        if not conn.execute(
            "SELECT 1 FROM person_registry WHERE person_id=?", (person_id,)
        ).fetchone():
            raise HTTPException(404, f"Person {person_id} not found")
        # Account already owned by a different person?
        conflict = _account_owner_elsewhere(conn, account_no, person_id)
        if conflict:
            raise HTTPException(409, _conflict_message(conflict, "add"))
    else:
        # NEVER link on name alone. Rider names collide constantly ("Amit
        # Naskar" exists at two companies as two different people) and a
        # silent merge corrupts both ledgers — this used to attach any new
        # rider to the first person with the same display_name. A new rider
        # without an explicit person_id gets a NEW person; attaching to an
        # existing one is a deliberate act (pass person_id, or use the
        # onboarding "link" action). Any existing holder of this bank
        # account is still a conflict, and the 409 names the owner so the
        # operator can link explicitly if it really is the same person.
        conflict = _account_owner_elsewhere(conn, account_no, None)
        if conflict:
            raise HTTPException(409, _conflict_message(conflict, "create"))
        cur = conn.execute(
            "INSERT INTO person_registry (display_name, deduction_company, deduction_rider_id) "
            "VALUES (?,?,?)",
            (name, company, rider_id),
        )
        person_id = cur.lastrowid
        _init_person(conn, person_id)
    # Default to BIKE when nothing was supplied — that's the safe assumption
    # for any rider not on an EV. (The runtime display value is still derived
    # from EV-assignment status in list/lookup queries, so this is mostly for
    # raw exports and any future direct selects on rider_master.)
    veh = (vehicle or "").strip().upper() or "BIKE"
    conn.execute(
        "INSERT INTO rider_master (rider_id, company, person_id, name, hub, vehicle, "
        "account_no, ifsc) VALUES (?,?,?,?,?,?,?,?)",
        (rider_id, company, person_id, name, hub, veh, account_no, ifsc),
    )
    return True, rider_id, person_id


@router.post("/rename-rider-id")
def rename_rider_id(body: RenameRiderIdIn, _: dict = Depends(require_admin)) -> dict:
    """Attach a real rider_id to a placeholder QSPEND row (or rename any
    rider_id, really). Updates rider_master + every reference in transactions
    so history is preserved. The new rider_id must not already exist for
    the same company."""
    new_rid = body.new_rider_id.strip()
    if not new_rid:
        raise HTTPException(400, "new_rider_id is required")
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT rider_id FROM rider_master WHERE person_id=? AND company=?",
            (body.person_id, body.company),
        ).fetchall()
        if not rows:
            raise HTTPException(404, f"Person {body.person_id} has no rider at {body.company}")
        # Pick which existing rider_id we're renaming.
        if body.current_rider_id:
            current = body.current_rider_id
            if current not in [r["rider_id"] for r in rows]:
                raise HTTPException(
                    404,
                    f"Rider {current!r} not found for person {body.person_id} at {body.company}",
                )
        elif len(rows) == 1:
            current = rows[0]["rider_id"]
        else:
            raise HTTPException(
                409,
                f"Person {body.person_id} has {len(rows)} rider_ids at "
                f"{body.company}; specify current_rider_id "
                f"(one of {[r['rider_id'] for r in rows]})",
            )
        if current == new_rid:
            return {"renamed": False, "reason": "Same value", "rider_id": new_rid}
        # Refuse if the target is already taken at this company.
        clash = conn.execute(
            "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
            (new_rid, body.company),
        ).fetchone()
        if clash:
            raise HTTPException(
                409,
                f"rider_id {new_rid!r} already exists at {body.company} "
                f"(person {clash['person_id']}). Use Link Riders to merge instead.",
            )
        conn.execute(
            "UPDATE rider_master SET rider_id=? WHERE rider_id=? AND company=?",
            (new_rid, current, body.company),
        )
        conn.execute(
            "UPDATE transactions SET rider_id=? WHERE rider_id=? AND company=?",
            (new_rid, current, body.company),
        )
        # cod_holds is per-cycle but indexed by rider_id too.
        conn.execute(
            "UPDATE cod_holds SET rider_id=? WHERE rider_id=? AND company=?",
            (new_rid, current, body.company),
        )
        # person_registry.deduction_rider_id may also hold the old value.
        conn.execute(
            "UPDATE person_registry SET deduction_rider_id=? "
            "WHERE deduction_rider_id=? AND deduction_company=?",
            (new_rid, current, body.company),
        )
        conn.commit()
    return {
        "renamed": True,
        "person_id": body.person_id,
        "company": body.company,
        "old_rider_id": current,
        "new_rider_id": new_rid,
    }


@router.post("/export")
def export_riders(
    company: str | None = None,
    hub: str | None = None,
    active: bool | None = None,
    body: ExportSelection = Body(default=ExportSelection()),
    _: dict = Depends(get_current_user),
):
    """Riders as a styled .xlsx download. Honours the same filters as the
    list endpoint so the export matches the on-screen scope."""
    where, params = ["1=1"], []
    if company is not None:
        where.append("rm.company=?")
        params.append(company)
    if hub is not None:
        where.append("rm.hub=?")
        params.append(hub)
    if active is not None:
        where.append("rm.is_active=?")
        params.append(1 if active else 0)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT rm.person_id, rm.rider_id, rm.company, rm.name, rm.hub, "
            f"       CASE WHEN ea.assignment_id IS NOT NULL THEN 'EV' ELSE 'BIKE' END AS vehicle, "
            f"       rm.account_no, rm.ifsc, rm.mob_no, rm.is_active "
            f"FROM rider_master rm "
            f"LEFT JOIN ev_assignments ea "
            f"  ON ea.person_id = rm.person_id AND ea.returned_date IS NULL "
            f"WHERE {' AND '.join(where)} ORDER BY rm.name, rm.company",
            params,
        ).fetchall()
    headers = [
        "Person ID",
        "Rider ID",
        "Company",
        "Name",
        "Hub",
        "Vehicle",
        "Account No",
        "IFSC",
        "Active",
    ]
    out = [
        (
            r["person_id"],
            r["rider_id"],
            r["company"],
            r["name"] or "",
            r["hub"] or "",
            r["vehicle"],
            r["account_no"] or "",
            r["ifsc"] or "",
            "yes" if r["is_active"] else "no",
        )
        for r in rows
        if body.ids is None or f"{r['rider_id']}|{r['company']}" in {str(x) for x in body.ids}
    ]
    return xlsx_response(
        filename_stem="riders",
        sheet_name="RIDERS",
        headers=headers,
        rows=out,
        left_align_cols=(4, 5, 7, 8),
    )


@router.get("", response_model=list[RiderOut])
def list_riders(
    company: str | None = None,
    hub: str | None = None,
    active: bool | None = None,
    _: dict = Depends(get_current_user),
) -> list[RiderOut]:
    """List riders. The ``vehicle`` column is derived from whether the rider's
    person currently holds an open ev_assignment — ``EV`` when they do,
    ``BIKE`` otherwise — independent of whatever was set at rider creation."""
    where, params = ["1=1"], []
    if company is not None:
        where.append("rm.company=?")
        params.append(company)
    if hub is not None:
        where.append("rm.hub=?")
        params.append(hub)
    if active is not None:
        where.append("rm.is_active=?")
        params.append(1 if active else 0)
    with get_connection() as conn:
        rows = conn.execute(
            f"SELECT rm.rider_id, rm.company, rm.person_id, rm.name, rm.hub, "
            f"       CASE WHEN ea.assignment_id IS NOT NULL THEN 'EV' ELSE 'BIKE' END AS vehicle, "
            f"       rm.account_no, rm.ifsc, rm.mob_no, rm.is_active "
            f"FROM rider_master rm "
            f"LEFT JOIN ev_assignments ea "
            f"  ON ea.person_id = rm.person_id AND ea.returned_date IS NULL "
            f"WHERE {' AND '.join(where)} ORDER BY rm.name, rm.company",
            params,
        ).fetchall()
    return [RiderOut(**_rider_dict(r)) for r in rows]


@router.patch("/{rider_id}", response_model=RiderOut)
def update_rider(
    rider_id: str, body: RiderPatch, company: str = Query(...), _: dict = Depends(require_admin)
) -> RiderOut:
    """Partially update a rider — only the fields you send are changed.

    ``new_rider_id`` / ``new_company`` rename the primary key; the change
    cascades to transactions, cod_holds and person_registry.deduction_*.
    IFSC and vehicle are uppercased; empty strings become NULL.
    """
    fields: dict = {}
    if body.name is not None:
        fields["name"] = body.name.strip() or None
    if body.hub is not None:
        fields["hub"] = body.hub.strip() or None
    if body.vehicle is not None:
        fields["vehicle"] = body.vehicle.strip().upper() or None
    if body.account_no is not None:
        fields["account_no"] = body.account_no.strip() or None
    if body.ifsc is not None:
        fields["ifsc"] = body.ifsc.strip().upper() or None
    if body.mob_no is not None:
        fields["mob_no"] = body.mob_no.strip() or None
    if body.is_active is not None:
        fields["is_active"] = 1 if body.is_active else 0

    new_rid = (body.new_rider_id or "").strip() or None
    new_co = (body.new_company or "").strip() or None

    if not fields and not new_rid and not new_co:
        raise HTTPException(400, "Nothing to update")

    with get_connection() as conn:
        existing = conn.execute(
            "SELECT * FROM rider_master WHERE rider_id=? AND company=?",
            (rider_id, company),
        ).fetchone()
        if not existing:
            raise HTTPException(404, "Rider not found")

        # If account_no is being changed, make sure we're not stealing it from
        # another person.
        if "account_no" in fields and fields["account_no"]:
            conflict = _account_owner_elsewhere(conn, fields["account_no"], existing["person_id"])
            if conflict:
                raise HTTPException(409, _conflict_message(conflict, "save"))

        # Plain-column updates first.
        if fields:
            sets = [f"{k}=?" for k in fields]
            params = list(fields.values()) + [rider_id, company]
            conn.execute(
                f"UPDATE rider_master SET {', '.join(sets)}, updated_at=datetime('now') "
                f"WHERE rider_id=? AND company=?",
                params,
            )

        # PK rename (rider_id and/or company).
        if new_rid or new_co:
            target_rid = new_rid or rider_id
            target_co = new_co or company
            if (
                new_co
                and not conn.execute(
                    "SELECT 1 FROM companies WHERE company_name=?", (target_co,)
                ).fetchone()
            ):
                raise HTTPException(400, f"Unknown company {target_co!r}")
            if (target_rid, target_co) != (rider_id, company):
                clash = conn.execute(
                    "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
                    (target_rid, target_co),
                ).fetchone()
                if clash:
                    raise HTTPException(
                        409,
                        f"({target_rid}, {target_co}) already exists "
                        f"(person {clash['person_id']}). Use Link Riders to merge.",
                    )
                conn.execute(
                    "UPDATE rider_master SET rider_id=?, company=? WHERE rider_id=? AND company=?",
                    (target_rid, target_co, rider_id, company),
                )
                conn.execute(
                    "UPDATE transactions SET rider_id=?, company=? WHERE rider_id=? AND company=?",
                    (target_rid, target_co, rider_id, company),
                )
                conn.execute(
                    "UPDATE cod_holds SET rider_id=?, company=? WHERE rider_id=? AND company=?",
                    (target_rid, target_co, rider_id, company),
                )
                conn.execute(
                    "UPDATE person_registry SET deduction_rider_id=?, deduction_company=? "
                    "WHERE deduction_rider_id=? AND deduction_company=?",
                    (target_rid, target_co, rider_id, company),
                )
                rider_id, company = target_rid, target_co  # for the SELECT below

        row = conn.execute(
            "SELECT rider_id, company, person_id, name, hub, vehicle, account_no, ifsc, is_active "
            "FROM rider_master WHERE rider_id=? AND company=?",
            (rider_id, company),
        ).fetchone()
        conn.commit()
    return RiderOut(**_rider_dict(row))


@router.delete("/{rider_id}")
def delete_rider(
    rider_id: str, company: str = Query(...), _: dict = Depends(require_admin)
) -> dict:
    """Delete one (rider_id, company) mapping.

    Only the workbook mapping goes — the person, their balances, transactions,
    COD history and EV assignments are all keyed by person_id and stay intact.
    If the deleted id was the person's deduction anchor, the anchor moves to
    one of their remaining rider ids (or clears when none remain). Payout
    workbooks carrying this rider_id will land as unknown riders afterwards —
    that's the point of deleting a bad id.

    (The audit middleware records who deleted what, as with every DELETE.)
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT person_id FROM rider_master WHERE rider_id=? AND company=?",
            (rider_id, company),
        ).fetchone()
        if not row:
            raise HTTPException(404, "Rider not found")
        pid = row["person_id"]

        conn.execute("DELETE FROM rider_master WHERE rider_id=? AND company=?", (rider_id, company))

        remaining = conn.execute(
            "SELECT rider_id, company FROM rider_master WHERE person_id=? "
            "ORDER BY is_active DESC, updated_at DESC",
            (pid,),
        ).fetchall()

        # Re-anchor the deduction pointer if it referenced the deleted id.
        anchor = conn.execute(
            "SELECT deduction_rider_id, deduction_company FROM person_registry WHERE person_id=?",
            (pid,),
        ).fetchone()
        deduction_moved_to = None
        if (
            anchor
            and anchor["deduction_rider_id"] == rider_id
            and anchor["deduction_company"] == company
        ):
            if remaining:
                deduction_moved_to = {
                    "rider_id": remaining[0]["rider_id"],
                    "company": remaining[0]["company"],
                }
                conn.execute(
                    "UPDATE person_registry SET deduction_rider_id=?, deduction_company=? "
                    "WHERE person_id=?",
                    (remaining[0]["rider_id"], remaining[0]["company"], pid),
                )
            else:
                conn.execute(
                    "UPDATE person_registry SET deduction_rider_id=NULL, deduction_company=NULL "
                    "WHERE person_id=?",
                    (pid,),
                )
        conn.commit()
    return {
        "deleted": {"rider_id": rider_id, "company": company},
        "person_id": pid,
        "remaining_rider_ids": len(remaining),
        "deduction_moved_to": deduction_moved_to,
    }


@router.get("/{rider_id}", response_model=RiderOut)
def get_rider(
    rider_id: str, company: str = Query(...), _: dict = Depends(get_current_user)
) -> RiderOut:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT rider_id, company, person_id, name, hub, vehicle, account_no, ifsc, is_active "
            "FROM rider_master WHERE rider_id=? AND company=?",
            (rider_id, company),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Rider not found")
    return RiderOut(**_rider_dict(row))


@router.post("", response_model=RiderOut, status_code=201)
def create_rider(body: RiderIn, _: dict = Depends(require_admin)) -> RiderOut:
    """Create a rider. ``rider_id`` is optional — when blank we assign a
    placeholder (``QSPEND<NNNN>`` scoped per company). When ``person_id`` is
    supplied the new rider_master row is attached to that existing person —
    used when adding a person to a second company. Duplicate detection
    on (name, company) and (account_no, company) is skipped when person_id
    is explicit, because attaching to a known person is the intent."""
    with get_connection() as conn:
        if body.person_id is None:
            existing = _find_existing_rider(conn, body.name, body.company, body.account_no)
            if existing:
                raise HTTPException(
                    409,
                    f"{body.name!r} already exists at {body.company} "
                    f"(rider_id={existing['rider_id']}). "
                    f"Use 'Link Riders' to merge if this is intentional.",
                )
        _, rider_id, person_id = _insert_rider_into_db(
            conn,
            rider_id=body.rider_id,
            company=body.company,
            name=body.name,
            hub=body.hub,
            vehicle=body.vehicle,
            account_no=body.account_no,
            ifsc=body.ifsc,
            person_id=body.person_id,
        )
        conn.commit()
    return RiderOut(
        rider_id=rider_id,
        company=body.company,
        person_id=person_id,
        name=body.name,
        hub=body.hub,
        vehicle=body.vehicle,
        account_no=body.account_no,
        ifsc=body.ifsc,
        is_active=True,
    )


@router.post("/bulk")
def bulk_create_riders(
    file: UploadFile = File(...),
    commit: bool = Query(False, description="Set true to actually write"),
    _: dict = Depends(require_admin),
) -> dict:
    """Bulk-add riders from an Excel file. Columns accepted:

      rider_id | company | name | hub | vehicle | account_no | ifsc

    All except company + name are optional; rider_id blank → auto placeholder.
    Rows that match an existing (name, company) or (account_no, company) are
    skipped and reported. Unknown companies are skipped. Whole import is one
    transaction — if anything raises, nothing is written.
    """
    data = file.file.read()
    try:
        df = pd.read_excel(BytesIO(data))
    except Exception as exc:
        raise HTTPException(400, f"Could not read Excel: {exc}") from exc
    df.columns = [str(c).strip() for c in df.columns]
    cols = {
        "rid": match_column(df.columns, "rider_id", "rider id", "riderid"),
        "co": match_column(df.columns, "company"),
        "name": match_column(df.columns, "rider_name", "rider name", "name"),
        "hub": match_column(df.columns, "hub"),
        "veh": match_column(df.columns, "vehicle", "vehicle type"),
        "acc": match_column(df.columns, "account_no", "account no", "acc_no", "account number"),
        "ifsc": match_column(df.columns, "ifsc", "ifsc code"),
    }
    if not cols["co"] or not cols["name"]:
        raise HTTPException(
            400,
            f"Bulk upload needs at least 'company' + 'name' columns. Found {list(df.columns)}",
        )

    def cell(row, key):
        col = cols[key]
        if not col:
            return None
        v = row.get(col)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip()
        return s if s and s.lower() != "nan" else None

    created: list[dict] = []
    duplicates: list[dict] = []
    skipped: list[dict] = []
    errors: list[str] = []

    with get_connection() as conn:
        known_co = {r["company_name"] for r in conn.execute("SELECT company_name FROM companies")}
        for i, row in df.iterrows():
            line = int(i) + 2  # 1-based + header
            name = cell(row, "name")
            co = cell(row, "co")
            if not name or not co:
                skipped.append({"line": line, "reason": "missing name or company"})
                continue
            if co not in known_co:
                skipped.append({"line": line, "reason": f"unknown company {co!r}"})
                continue
            existing = _find_existing_rider(conn, name, co, cell(row, "acc"))
            if existing:
                duplicates.append(
                    {
                        "line": line,
                        "name": name,
                        "company": co,
                        "existing_rider_id": existing["rider_id"],
                    }
                )
                continue
            try:
                _, rid, pid = _insert_rider_into_db(
                    conn,
                    rider_id=cell(row, "rid"),
                    company=co,
                    name=name,
                    hub=cell(row, "hub"),
                    vehicle=cell(row, "veh"),
                    account_no=cell(row, "acc"),
                    ifsc=cell(row, "ifsc"),
                )
                created.append(
                    {
                        "line": line,
                        "rider_id": rid,
                        "company": co,
                        "name": name,
                        "person_id": pid,
                    }
                )
            except HTTPException as e:
                errors.append(f"line {line}: {e.detail}")
        if commit and not errors:
            conn.commit()
        else:
            conn.rollback()
    return {
        "committed": commit and not errors,
        "summary": {
            "would_create": len(created),
            "duplicates": len(duplicates),
            "skipped": len(skipped),
            "errors": len(errors),
        },
        "created": created,
        "duplicates": duplicates,
        "skipped": skipped,
        "errors": errors,
    }


_UPDATABLE = ("name", "hub", "vehicle", "account_no", "ifsc")


@router.post("/bulk-update")
def bulk_update_riders(
    file: UploadFile = File(...),
    commit: bool = Query(False, description="Set true to actually write"),
    match_by: str = Query(
        "rider_id+company",
        description="Either 'rider_id+company' or 'account_no+company'.",
    ),
    _: dict = Depends(require_admin),
) -> dict:
    """Bulk-update existing rider details from an Excel or CSV file.

    Required columns depend on ``match_by``:
      - rider_id+company (default): the file must have rider_id + company
      - account_no+company:         the file must have account_no + company

    Any subset of the updatable columns may be present and only non-blank
    cells are written — leaving a cell empty leaves the stored value alone.
    Updatable columns: name | hub | vehicle | account_no | ifsc

    Dry-run by default. Pass ``?commit=true`` to actually persist.
    """
    data = file.file.read()
    df = None
    name_lower = (file.filename or "").lower()
    try:
        if name_lower.endswith(".csv") or name_lower.endswith(".tsv"):
            sep = "\t" if name_lower.endswith(".tsv") else ","
            df = pd.read_csv(BytesIO(data), sep=sep, dtype=str, keep_default_na=False)
        else:
            df = pd.read_excel(BytesIO(data), dtype=str)
    except Exception as exc:
        raise HTTPException(400, f"Could not read file: {exc}") from exc

    df.columns = [str(c).strip() for c in df.columns]
    cols = {
        "rid": match_column(df.columns, "rider_id", "rider id", "riderid"),
        "co": match_column(df.columns, "company"),
        "name": match_column(df.columns, "rider_name", "rider name", "name"),
        "hub": match_column(df.columns, "hub"),
        "veh": match_column(df.columns, "vehicle", "vehicle type"),
        "acc": match_column(
            df.columns, "account_no", "account no", "acc_no", "account number", "a/c no", "ac no"
        ),
        "ifsc": match_column(df.columns, "ifsc", "ifsc code"),
    }
    if not cols["co"]:
        raise HTTPException(400, "Missing required 'company' column.")
    if match_by == "rider_id+company" and not cols["rid"]:
        raise HTTPException(400, "match_by=rider_id+company needs a 'rider_id' column.")
    if match_by == "account_no+company" and not cols["acc"]:
        raise HTTPException(400, "match_by=account_no+company needs an 'account_no' column.")
    if match_by not in ("rider_id+company", "account_no+company"):
        raise HTTPException(400, f"Unknown match_by={match_by!r}")

    def cell(row, key):
        col = cols[key]
        if not col:
            return None
        v = row.get(col)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return None
        s = str(v).strip()
        return s if s and s.lower() != "nan" else None

    updated: list[dict] = []
    unchanged: list[dict] = []
    not_found: list[dict] = []
    errors: list[str] = []

    with get_connection() as conn:
        for i, row in df.iterrows():
            line = int(i) + 2
            co = cell(row, "co")
            if not co:
                errors.append(f"line {line}: missing company")
                continue

            # Locate the rider row.
            if match_by == "rider_id+company":
                rid = cell(row, "rid")
                if not rid:
                    errors.append(f"line {line}: missing rider_id")
                    continue
                cur = conn.execute(
                    "SELECT * FROM rider_master WHERE rider_id=? AND company=?",
                    (rid, co),
                ).fetchone()
            else:
                acc = cell(row, "acc")
                cur = conn.execute(
                    "SELECT * FROM rider_master "
                    "WHERE account_no=? AND company=? AND account_no <> ''",
                    (acc, co),
                ).fetchone()
            if cur is None:
                not_found.append(
                    {"line": line, "company": co, "key": cell(row, "rid") or cell(row, "acc")}
                )
                continue

            patch: dict[str, str] = {}
            for field, key in (
                ("name", "name"),
                ("hub", "hub"),
                ("vehicle", "veh"),
                ("account_no", "acc"),
                ("ifsc", "ifsc"),
            ):
                v = cell(row, key)
                if v is not None and (cur[field] or "") != v:
                    if field == "ifsc":
                        v = v.upper()
                    patch[field] = v
            if not patch:
                unchanged.append({"line": line, "rider_id": cur["rider_id"], "company": co})
                continue
            # Block account theft from another person.
            if "account_no" in patch and patch["account_no"]:
                conflict = _account_owner_elsewhere(conn, patch["account_no"], cur["person_id"])
                if conflict:
                    errors.append(f"line {line}: {_conflict_message(conflict, 'save')}")
                    continue
            sets = ", ".join(f"{f}=?" for f in patch)
            params = list(patch.values()) + [cur["rider_id"], co]
            conn.execute(
                f"UPDATE rider_master SET {sets} WHERE rider_id=? AND company=?",
                params,
            )
            updated.append(
                {
                    "line": line,
                    "rider_id": cur["rider_id"],
                    "company": co,
                    "fields": list(patch.keys()),
                    "values": patch,
                }
            )
        if commit and not errors:
            conn.commit()
        else:
            conn.rollback()

    return {
        "committed": commit and not errors,
        "match_by": match_by,
        "summary": {
            "would_update": len(updated),
            "unchanged": len(unchanged),
            "not_found": len(not_found),
            "errors": len(errors),
        },
        "updated": updated,
        "unchanged": unchanged,
        "not_found": not_found,
        "errors": errors,
    }


@router.post("/onboard-unknowns")
def onboard_unknowns(payload: dict, _: dict = Depends(require_admin)) -> dict:
    """Resolve a batch of unknown rider_ids surfaced by a payout preview.

    Body shape::

        {
          "company": "Spencer's",
          "rows": [
            {"rider_id": "8906377190",
             "action": "create",                  # default
             "name": "Bapan Singh", "hub": "NTS",
             "account_no": "123...", "ifsc": "SBI0...",
             "vehicle": "BIKE"},

            {"rider_id": "8906377155",
             "action": "link",
             "link_to_person_id": 224},           # OR:
            # "link_to_rider_id": "8906377101"    # any rider already in DB
          ]
        }

    All resolutions are written in one transaction so a single failure rolls
    back the lot. Returns counts + per-row results.
    """
    company = (payload.get("company") or "").strip()
    if not company:
        raise HTTPException(400, "company is required")
    rows = payload.get("rows") or []
    if not isinstance(rows, list) or not rows:
        raise HTTPException(400, "rows must be a non-empty list")

    created: list[dict] = []
    linked: list[dict] = []
    errors: list[str] = []

    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM companies WHERE company_name=?", (company,)).fetchone():
            raise HTTPException(400, f"Unknown company {company!r}")

        for i, row in enumerate(rows, 1):
            rider_id = (row.get("rider_id") or "").strip()
            if not rider_id:
                errors.append(f"row {i}: rider_id missing")
                continue
            action = (row.get("action") or "create").strip().lower()

            if action == "link":
                pid = row.get("link_to_person_id")
                if not pid and row.get("link_to_rider_id"):
                    pr = conn.execute(
                        "SELECT person_id FROM rider_master WHERE rider_id=? LIMIT 1",
                        (row["link_to_rider_id"],),
                    ).fetchone()
                    if pr:
                        pid = pr["person_id"]
                if not pid:
                    errors.append(f"row {i} ({rider_id}): no link target found")
                    continue
                if not conn.execute(
                    "SELECT 1 FROM person_registry WHERE person_id=?", (pid,)
                ).fetchone():
                    errors.append(f"row {i} ({rider_id}): person {pid} not found")
                    continue
                # Pull display name from the existing person so the new
                # rider_master row carries a sane name.
                target = conn.execute(
                    "SELECT display_name FROM person_registry WHERE person_id=?", (pid,)
                ).fetchone()
                try:
                    _, new_rid, new_pid = _insert_rider_into_db(
                        conn,
                        rider_id=rider_id,
                        company=company,
                        name=row.get("name") or target["display_name"],
                        hub=row.get("hub"),
                        vehicle=row.get("vehicle") or "BIKE",
                        account_no=row.get("account_no"),
                        ifsc=(row.get("ifsc") or "").upper() or None,
                        person_id=int(pid),
                    )
                    linked.append({"rider_id": new_rid, "person_id": new_pid})
                except HTTPException as e:
                    errors.append(f"row {i} ({rider_id}): {e.detail}")
                continue

            # action == "create" — make a new person + rider
            name = (row.get("name") or "").strip()
            if not name:
                errors.append(f"row {i} ({rider_id}): name required for create")
                continue
            try:
                _, new_rid, new_pid = _insert_rider_into_db(
                    conn,
                    rider_id=rider_id,
                    company=company,
                    name=name,
                    hub=row.get("hub"),
                    vehicle=row.get("vehicle") or "BIKE",
                    account_no=row.get("account_no"),
                    ifsc=(row.get("ifsc") or "").upper() or None,
                )
                created.append({"rider_id": new_rid, "person_id": new_pid, "name": name})
            except HTTPException as e:
                errors.append(f"row {i} ({rider_id}): {e.detail}")

        if errors:
            conn.rollback()
        else:
            conn.commit()

    return {
        "committed": not errors,
        "summary": {
            "created": len(created),
            "linked": len(linked),
            "errors": len(errors),
        },
        "created": created,
        "linked": linked,
        "errors": errors,
    }
