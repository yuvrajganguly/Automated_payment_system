"""Pydantic schemas for API requests and responses."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


# ── Auth ────────────────────────────────────────────────────────────────────
class ExportSelection(BaseModel):
    """Optional filtered scope for an export: only these row ids."""

    ids: list[str | int] | None = None


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    email: str


class UserOut(BaseModel):
    email: str
    role: str
    phone: str | None = None


# ── Companies ───────────────────────────────────────────────────────────────
class CompanyOut(BaseModel):
    company_name: str
    parser_type: str
    payout_column: str
    has_hold_sheet: bool
    hold_style: str | None = None
    is_active: bool
    # Another company whose rider IDs this one reuses (Nykaa -> Blitz).
    rider_ids_shared_with: str | None = None


# ── Riders + Persons ────────────────────────────────────────────────────────
class RiderIn(BaseModel):
    rider_id: str | None = None  # empty/None → auto-generated placeholder
    company: str
    name: str
    hub: str | None = None
    vehicle: str | None = None
    account_no: str | None = None
    ifsc: str | None = None
    # Attach this new rider_master row to an existing person, instead of
    # creating a fresh one by display_name lookup. Used when adding a person
    # to a second company.
    person_id: int | None = None


class RiderOut(BaseModel):
    rider_id: str
    company: str
    person_id: int
    name: str | None = None
    hub: str | None = None
    vehicle: str | None = None
    account_no: str | None = None
    ifsc: str | None = None
    mob_no: str | None = None
    is_active: bool = True


class RiderPatch(BaseModel):
    """Partial update of a rider_master row. Send only the fields you want
    to change. Any field that's a column of rider_master is editable — including
    rider_id and company. Changes to those will cascade through transactions,
    cod_holds and person_registry.deduction_*."""

    name: str | None = None
    hub: str | None = None
    vehicle: str | None = None
    account_no: str | None = None
    ifsc: str | None = None
    mob_no: str | None = None
    is_active: bool | None = None
    new_rider_id: str | None = None
    new_company: str | None = None


class EvSummary(BaseModel):
    ev_id: str
    provider: str
    model: str
    weekly_rate: float
    handover_date: str | None = None
    rent_charged_through: str | None = None


class EvHistoryItem(BaseModel):
    assignment_id: int
    ev_id: str
    provider: str | None = None
    model: str | None = None
    weekly_rate: float
    handover_date: str | None = None
    returned_date: str | None = None
    rent_charged_through: str | None = None


class PersonOut(BaseModel):
    person_id: int
    display_name: str
    deduction_company: str | None = None
    deduction_rider_id: str | None = None
    # None for recruiters — they never see money.
    current_balance: float | None = None
    arrears_outstanding: float | None = None
    riders: list[RiderOut] = Field(default_factory=list)
    ev: EvSummary | None = None
    # Closed + open EV assignments, newest first. Carried on the model so the
    # `-> PersonOut` response filter doesn't strip it (it used to: the handler
    # merged ev_history on top of the model and FastAPI dropped the unknown
    # key, so no rider ever showed EV history).
    ev_history: list[EvHistoryItem] = Field(default_factory=list)


class SplitRiderSpec(BaseModel):
    rider_id: str
    company: str


class SplitPersonIn(BaseModel):
    """Carve one or more rider_master rows out of a person into a brand-new
    person. The new person inherits whatever ledger you opt to transfer; the
    rest stays on the original."""

    rider_ids: list[SplitRiderSpec]
    new_display_name: str | None = None
    transfer_open_ev: bool = False  # move the open ev_assignment to the new person
    transfer_balance_fraction: float = 0.0  # 0 = keep with source, 1 = move all to new
    transfer_arrears_fraction: float = 0.0


class LinkRidersIn(BaseModel):
    # Person-ID based: pick two people from the Riders page and merge.
    # rider_id-based fields are kept optional for backwards compatibility.
    primary_person_id: int | None = None
    secondary_person_id: int | None = None
    primary_rider_id: str | None = None
    primary_company: str | None = None
    secondary_rider_id: str | None = None
    secondary_company: str | None = None


class RenameRiderIdIn(BaseModel):
    """Attach a real rider_id to a placeholder (e.g. QSPEND0001 → 67163_MNOW000312).
    The (current rider_id, company) pair is renamed in place; all references in
    transactions, ev_assignments and rider_master follow."""

    person_id: int
    company: str
    new_rider_id: str
    # Optional: if you know which placeholder you're targeting, name it. Otherwise
    # the route picks the only rider_id this person has at that company (errors
    # if there's more than one).
    current_rider_id: str | None = None


# ── EVs ─────────────────────────────────────────────────────────────────────
class EvModelOut(BaseModel):
    model_id: int
    provider: str
    model_name: str
    weekly_rate: float


class EvUnitIn(BaseModel):
    ev_id: str
    provider: str
    model: str
    notes: str | None = None
    # Optional: bind this new unit to a person right away.
    person_id: int | None = None
    handover_date: date | None = None


class EvUnitOut(BaseModel):
    ev_id: str
    provider: str
    model: str
    weekly_rate: float
    status: str
    notes: str | None = None
    current_rider_id: str | None = None
    current_person_id: int | None = None
    current_rider_name: str | None = None
    hub: str | None = None
    handover_date: str | None = None
    rent_charged_through: str | None = None


class EvAssignIn(BaseModel):
    """Assign an EV to a person — either directly by ``person_id`` or via a
    (rider_id, company) pair. Person ID is the unambiguous handle (a person
    can ride for several companies; names and rider IDs collide)."""

    ev_id: str
    person_id: int | None = None
    rider_id: str | None = None
    company: str | None = None
    handover_date: date | None = None


class BackrentIn(BaseModel):
    ev_id: str
    amount: float | None = None  # rupees; omit to use the computed amount


class EvReturnIn(BaseModel):
    rider_id: str | None = None
    company: str | None = None
    ev_id: str | None = None
    returned_date: date | None = None


class EvAmendReturnIn(BaseModel):
    """Correct the return date of an ALREADY-closed assignment to an earlier
    day (news of a return often arrives after someone clicked Return with
    today's date). The books heal the same way as a backdated return."""

    ev_id: str
    returned_date: date


class MaintenanceIn(BaseModel):
    ev_id: str
    from_date: date
    to_date: date | None = None  # open-ended ('still in maintenance')
    reason: str | None = None


class MaintenanceClose(BaseModel):
    to_date: date | None = None  # default: today


class MaintenanceOut(BaseModel):
    id: int
    ev_id: str
    from_date: str
    to_date: str | None = None
    reason: str | None = None
    created_by: str | None = None
    created_at: str | None = None


# ── Ledger ──────────────────────────────────────────────────────────────────
class TransactionOut(BaseModel):
    id: int
    person_id: int
    rider_id: str | None = None
    company: str | None = None
    cycle_start: str
    cycle_end: str
    event_type: str
    amount: float
    balance_after: float
    days: int | None = None
    remarks: str | None = None
    created_at: str | None = None
    created_by: str | None = None


class AdjustmentIn(BaseModel):
    rider_id: str | None = None
    person_id: int | None = None
    company: str | None = None
    amount: float
    reason: str


class RentPaymentIn(BaseModel):
    """Manual rent payment by a rider. The amount is split across outstanding
    EV-arrears first (RENT_RECOVERED), then current-cycle rent (RENT_COLLECTED),
    so it shows up correctly in EV Rent Details."""

    person_id: int | None = None
    rider_id: str | None = None
    company: str | None = None
    amount: float = Field(..., gt=0, description="Positive — amount the rider just paid.")
    paid_on: str | None = Field(None, description="ISO date the rider paid (defaults to today).")
    # Optional rent coverage window. When supplied, RENT_COLLECTED is logged
    # against this window (instead of the rider's last RENT cycle) and the EV's
    # rent_charged_through advances to period_end — so the next automated cycle
    # won't re-charge for the same days.
    period_start: str | None = Field(
        None, description="ISO date — start of the rent window this payment covers."
    )
    period_end: str | None = Field(
        None, description="ISO date — end (inclusive) of the rent window this payment covers."
    )
    remarks: str | None = None
    # Guardrail (01-Jul-2026 incident): the meter may only advance as far as
    # the money reaches. Advancing past that requires this explicit override —
    # e.g. a documented waiver — and should be rare.
    force_advance: bool = Field(
        False,
        description="Allow rent_charged_through to advance beyond what "
        "the paid amount covers. Requires a clear reason in remarks.",
    )


# ── Arrears ─────────────────────────────────────────────────────────────────
class ArrearsOut(BaseModel):
    person_id: int
    display_name: str
    ev_id: str | None = None
    model: str | None = None
    total_missed: float
    total_recovered: float
    outstanding: float
    last_updated: str | None = None


# ── Cycle overrides ─────────────────────────────────────────────────────────
class RiderOverrideIn(BaseModel):
    rider_id: str
    waive_days: int = 0
    waive_all: bool = False
    rent_override: float | None = None
    force_hold: bool = False
    force_release: bool = False


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str
