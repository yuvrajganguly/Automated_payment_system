"""Pydantic schemas for API requests and responses."""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, Field


# ── Auth ────────────────────────────────────────────────────────────────────
class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    email: str


class UserOut(BaseModel):
    email: str
    role: str


# ── Companies ───────────────────────────────────────────────────────────────
class CompanyOut(BaseModel):
    company_name: str
    parser_type: str
    payout_column: str
    has_hold_sheet: bool
    hold_style: Optional[str] = None
    is_active: bool


# ── Riders + Persons ────────────────────────────────────────────────────────
class RiderIn(BaseModel):
    rider_id: Optional[str] = None  # empty/None → auto-generated placeholder
    company: str
    name: str
    hub: Optional[str] = None
    vehicle: Optional[str] = None
    account_no: Optional[str] = None
    ifsc: Optional[str] = None
    # Attach this new rider_master row to an existing person, instead of
    # creating a fresh one by display_name lookup. Used when adding a person
    # to a second company.
    person_id: Optional[int] = None


class RiderOut(BaseModel):
    rider_id: str
    company: str
    person_id: int
    name: Optional[str] = None
    hub: Optional[str] = None
    vehicle: Optional[str] = None
    account_no: Optional[str] = None
    ifsc: Optional[str] = None
    is_active: bool = True


class RiderPatch(BaseModel):
    """Partial update of a rider_master row. Send only the fields you want
    to change. Any field that's a column of rider_master is editable — including
    rider_id and company. Changes to those will cascade through transactions,
    cod_holds and person_registry.deduction_*."""
    name: Optional[str] = None
    hub: Optional[str] = None
    vehicle: Optional[str] = None
    account_no: Optional[str] = None
    ifsc: Optional[str] = None
    is_active: Optional[bool] = None
    new_rider_id: Optional[str] = None
    new_company: Optional[str] = None


class EvSummary(BaseModel):
    ev_id: str
    provider: str
    model: str
    weekly_rate: float
    handover_date: Optional[str] = None
    rent_charged_through: Optional[str] = None


class PersonOut(BaseModel):
    person_id: int
    display_name: str
    deduction_company: Optional[str] = None
    deduction_rider_id: Optional[str] = None
    current_balance: float
    arrears_outstanding: float
    riders: list[RiderOut] = Field(default_factory=list)
    ev: Optional[EvSummary] = None


class SplitRiderSpec(BaseModel):
    rider_id: str
    company: str


class SplitPersonIn(BaseModel):
    """Carve one or more rider_master rows out of a person into a brand-new
    person. The new person inherits whatever ledger you opt to transfer; the
    rest stays on the original."""
    rider_ids: list[SplitRiderSpec]
    new_display_name: Optional[str] = None
    transfer_open_ev: bool = False     # move the open ev_assignment to the new person
    transfer_balance_fraction: float = 0.0  # 0 = keep with source, 1 = move all to new
    transfer_arrears_fraction: float = 0.0


class LinkRidersIn(BaseModel):
    # Person-ID based: pick two people from the Riders page and merge.
    # rider_id-based fields are kept optional for backwards compatibility.
    primary_person_id: Optional[int] = None
    secondary_person_id: Optional[int] = None
    primary_rider_id: Optional[str] = None
    primary_company: Optional[str] = None
    secondary_rider_id: Optional[str] = None
    secondary_company: Optional[str] = None


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
    current_rider_id: Optional[str] = None


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
    notes: Optional[str] = None
    # Optional: bind this new unit to a person right away.
    person_id: Optional[int] = None
    handover_date: Optional[date] = None


class EvUnitOut(BaseModel):
    ev_id: str
    provider: str
    model: str
    weekly_rate: float
    status: str
    notes: Optional[str] = None
    current_rider_id: Optional[str] = None
    current_person_id: Optional[int] = None
    current_rider_name: Optional[str] = None
    hub: Optional[str] = None
    handover_date: Optional[str] = None
    rent_charged_through: Optional[str] = None


class EvAssignIn(BaseModel):
    ev_id: str
    rider_id: str
    company: str
    handover_date: Optional[date] = None


class EvReturnIn(BaseModel):
    rider_id: Optional[str] = None
    company: Optional[str] = None
    ev_id: Optional[str] = None
    returned_date: Optional[date] = None


class MaintenanceIn(BaseModel):
    ev_id: str
    from_date: date
    to_date: Optional[date] = None  # open-ended ('still in maintenance')
    reason: Optional[str] = None


class MaintenanceClose(BaseModel):
    to_date: Optional[date] = None  # default: today


class MaintenanceOut(BaseModel):
    id: int
    ev_id: str
    from_date: str
    to_date: Optional[str] = None
    reason: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None


# ── Ledger ──────────────────────────────────────────────────────────────────
class TransactionOut(BaseModel):
    id: int
    person_id: int
    rider_id: Optional[str] = None
    company: Optional[str] = None
    cycle_start: str
    cycle_end: str
    event_type: str
    amount: float
    balance_after: float
    days: Optional[int] = None
    remarks: Optional[str] = None
    created_at: Optional[str] = None
    created_by: Optional[str] = None


class AdjustmentIn(BaseModel):
    rider_id: Optional[str] = None
    person_id: Optional[int] = None
    company: Optional[str] = None
    amount: float
    reason: str


class RentPaymentIn(BaseModel):
    """Manual rent payment by a rider. The amount is split across outstanding
    EV-arrears first (RENT_RECOVERED), then current-cycle rent (RENT_COLLECTED),
    so it shows up correctly in EV Rent Details."""
    person_id: Optional[int] = None
    rider_id: Optional[str] = None
    company: Optional[str] = None
    amount: float = Field(..., gt=0,
                          description="Positive — amount the rider just paid.")
    paid_on: Optional[str] = Field(
        None, description="ISO date the rider paid (defaults to today).")
    # Optional rent coverage window. When supplied, RENT_COLLECTED is logged
    # against this window (instead of the rider's last RENT cycle) and the EV's
    # rent_charged_through advances to period_end — so the next automated cycle
    # won't re-charge for the same days.
    period_start: Optional[str] = Field(
        None, description="ISO date — start of the rent window this payment covers.")
    period_end: Optional[str] = Field(
        None, description="ISO date — end (inclusive) of the rent window this payment covers.")
    remarks: Optional[str] = None


# ── Arrears ─────────────────────────────────────────────────────────────────
class ArrearsOut(BaseModel):
    person_id: int
    display_name: str
    ev_id: Optional[str] = None
    model: Optional[str] = None
    total_missed: float
    total_recovered: float
    outstanding: float
    last_updated: Optional[str] = None


# ── Cycle overrides ─────────────────────────────────────────────────────────
class RiderOverrideIn(BaseModel):
    rider_id: str
    waive_days: int = 0
    waive_all: bool = False
    rent_override: Optional[float] = None
    force_hold: bool = False
    force_release: bool = False


class ChangePasswordIn(BaseModel):
    current_password: str
    new_password: str
