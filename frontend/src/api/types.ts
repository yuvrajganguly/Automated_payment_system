export interface User { email: string; role: string }
export interface TokenResponse {
  access_token: string
  token_type: string
  role: string
  email: string
}

export interface Company {
  company_name: string
  parser_type: string
  payout_column: string
  has_hold_sheet: boolean
  hold_style: string | null
  is_active: boolean
  /** Another company whose rider IDs this one reuses (Nykaa -> Blitz). */
  rider_ids_shared_with?: string | null
}

export interface RiderResultRow {
  person_id: number
  rider_id: string
  name: string
  hub: string | null
  vehicle: string | null
  company: string
  ev_id: string | null
  model: string | null
  payout: number
  rent: number
  days: number
  arrears_recovered: number
  dues_cleared: number
  prev_balance: number
  released: number
  new_balance: number
  new_arrears: number
  cod_hold: number
  is_hold: boolean
  remarks: string
  account_no: string | null
  ifsc: string | null
  mob_no: string | null
}

export interface InactiveRow {
  person_id: number
  name: string
  rider_ids: string[]
  ev_id: string | null
  model: string | null
  current_balance: number
  arrears_outstanding: number
  reason: string
  vehicle: string | null
}

export interface CycleResult {
  company: string
  cycle_start: string
  cycle_end: string
  pay_rows: RiderResultRow[]
  dues_rows: RiderResultRow[]
  hold_rows: { rider_id: string; amount: number }[]
  inactive_rows: InactiveRow[]
  warnings: string[]
  unknown_ids: string[]
  unknown_riders: { rider_id: string; name: string; hub: string; payout: number }[]
  /** Riders in the file whose payout cell is not a number. Commit is refused while non-empty. */
  unreadable_riders: { rider_id: string; name: string; cell: string }[]
  /** Unknown ids that matched the company in `rider_ids_shared_with` and were linked automatically. */
  auto_linked: { rider_id: string; person_id: number; name: string; linked_from: string }[]
  committed: boolean
  totals: Record<string, number>
}

export interface RunResponse {
  result: CycleResult
  xlsx?: { filename: string; content_base64: string; mime: string }
}

export interface RiderOut {
  rider_id: string
  company: string
  person_id: number
  name: string | null
  hub: string | null
  vehicle: string | null
  account_no: string | null
  ifsc: string | null
  mob_no: string | null
  is_active: boolean
}

export interface EvSummary {
  ev_id: string
  provider: string
  model: string
  weekly_rate: number
  handover_date: string | null
  rent_charged_through: string | null
}

export interface EvHistoryEntry {
  assignment_id: number
  ev_id: string
  provider: string
  model: string
  weekly_rate: number
  handover_date: string | null
  returned_date: string | null
  rent_charged_through: string | null
}

export interface PersonOut {
  person_id: number
  display_name: string
  deduction_company: string | null
  deduction_rider_id: string | null
  current_balance: number
  arrears_outstanding: number
  riders: RiderOut[]
  ev: EvSummary | null
  ev_history?: EvHistoryEntry[]
}

export interface EvModelOut {
  model_id: number
  provider: string
  model_name: string
  weekly_rate: number
}

export interface EvUnitOut {
  ev_id: string
  provider: string
  model: string
  weekly_rate: number
  status: string
  notes: string | null
  current_rider_id: string | null
  current_person_id: number | null
  current_rider_name: string | null
  hub: string | null
  handover_date: string | null
  rent_charged_through: string | null
}

export interface MaintenanceOut {
  id: number
  ev_id: string
  from_date: string
  to_date: string | null   // NULL while the maintenance window is open (matches schemas.py)
  reason: string | null
  created_by: string | null
  created_at: string | null
}

export interface TransactionOut {
  id: number
  person_id: number
  rider_id: string | null
  company: string | null
  cycle_start: string
  cycle_end: string
  event_type: string
  amount: number
  balance_after: number
  days: number | null
  remarks: string | null
  created_at: string | null
  created_by: string | null
}

export interface ArrearsOut {
  person_id: number
  display_name: string
  ev_id: string | null
  model: string | null
  total_missed: number
  total_recovered: number
  outstanding: number
  last_updated: string | null
}
