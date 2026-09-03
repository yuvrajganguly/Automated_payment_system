# Payout Management System — Design Specification

> Living document. Captures the agreed data model, business rules, and file
> formats for the rebuild. Update this whenever a rule changes.
>
> Last updated: 2026-09-01 · Status: in production (steps 1–7 shipped; see §12)

---

## 1. Purpose

Internal tool that takes each delivery company's weekly payout file, deducts EV
rent, settles outstanding dues and EV back-rent, applies holds, and produces a
clean instruction sheet of who to pay and how much — backed by a permanent audit
trail.

Core complication: **one real person can hold many rider IDs** (across companies
and within one company), but rents only **one EV at a time**. Rent is charged
once per person; dues and missed EV rent follow the person across every company
and ID.

---

## 2. Glossary

- **person_id** — canonical identity; one real human.
- **rider_id** — an ID issued by a company. A person may have several.
- **deduction anchor** — the `(deduction_company, deduction_rider_id)` pair that
  says which company file + rider ID a person's EV rent is charged against. Moves
  automatically when that ID/company goes inactive (see cascading logic).
- **EV assignment** — a person holding a specific EV from a `handover_date` until
  a `returned_date`. The open assignment (no return date) is the current one and
  is the basis for rent proration.
- **arrears** — EV rent that could not be deducted (rider absent from payout);
  tracked separately from general dues and recovered from future payouts.
- **COD hold** — pending Cash-on-Delivery the rider is holding; flags the rider
  HOLD and records the amount. Not auto-deducted.
- **cycle** — the pay period (typically one week / 7 days); start + end dates are
  entered in the UI per file.

---

## 3. Companies

Active: **Dealshare, Myntra, Jiffy, Zepto, Blitz, Nykaa**. (Spencers removed.)
Zepto's file format is not yet known — parser deferred until a sample arrives.

**Nykaa** (added 2026-09) pays riders who also work for Blitz, under their
**Blitz rider IDs**. Its `companies` row sets `rider_ids_shared_with = 'Blitz'`:
when a Nykaa file contains a rider ID that is unknown for Nykaa but exists at
Blitz, the engine creates the Nykaa roster row pointing at the same person and
reports it under `auto_linked` instead of asking the operator to onboard
someone who already exists. The parser layout is **provisional** — cloned from
Blitz (`rider_id` / `net_pay` / `total_del`, no COD) until a real Nykaa file is
available; adjust the row with `payout-admin update-company --name Nykaa
--payout-col ... --rider-col ...` when it is.

---

## 4. EV providers & rate card

| Provider | Model    | Weekly rate | Daily rate (= weekly ÷ 7) |
|----------|----------|-------------|---------------------------|
| Raft     | Regular  | ₹1,250      | ₹178.57                   |
| Raft     | Blue     | ₹1,295      | ₹185.00                   |
| Blive    | Standard | ₹1,260      | ₹180.00                   |

Daily rate is always derived as weekly ÷ 7 (no separate stored daily rate).

---

## 5. Data model

### New tables

**`ev_models`** — rate card. `model_id`, `provider`, `model_name`, `weekly_rate`.
Seeded in code with the three models above.

**`ev_units`** — physical EVs. `ev_id` (PK), `model_id` → `ev_models`,
`status` (in_use / returned / spare), `notes`.

**`ev_assignments`** — who holds which EV and when. `assignment_id` (PK),
`person_id`, `ev_id`, `handover_date`, `returned_date` (NULL = current),
`created_at`. At most one open assignment per person. Source of rent proration;
EV swaps close one row and open another.

**`ev_arrears`** — the strict missed-rent tab. `person_id` (PK), `total_missed`,
`total_recovered`, `outstanding`, `last_updated`. Month-by-month detail is
reconstructable from `transactions` (RENT_MISSED / RENT_RECOVERED).

**`cod_holds`** — persisted COD/hold detail per cycle. `id` (PK),
`cycle_start`, `cycle_end`, `company`, `rider_id`, `person_id`, `worker_code`,
`order_number`, `amount`, `payment_mode`, `txn_status`, `source`
(`jiffy_sheet` | `myntra_column`), `created_at`. Per-rider hold total =
SUM(amount) for that rider in that cycle.

### Reshaped tables

**`companies`** — parser config. `company_name` (PK), `parser_type`,
`rider_ids_shared_with` (another company whose rider IDs this one reuses —
Nykaa → Blitz — so unknown IDs are auto-linked, see §3),
`payout_sheet` (sheet selector: index or name pattern), `rider_id_column`,
`payout_column`, `has_hold_sheet`, `hold_style` (`sheet` | `column`),
`hold_sheet`, `hold_key_column`, `hold_amount_column`, `hold_status_column`,
`is_active`. (DOJ / midweek columns removed.)

**`person_registry`** — `person_id` (PK), `display_name`, `kyc_no` (Aadhaar,
UNIQUE, nullable — added later), `deduction_company`, `deduction_rider_id`,
`created_at`. (EV fields moved to assignments.)

**`rider_master`** — `(rider_id, company)` (PK), `person_id`, `name`, `hub`,
`vehicle`, `account_no`, `ifsc`, `mob_no`, `email`, `is_active`,
`created_at`, `updated_at`. (DOJ removed; EV moved to assignments. Each row keeps
its own `name`, which preserves aliases after a merge.)

### Kept tables

**`transactions`** — immutable, append-only audit log. `id`, `person_id`,
`rider_id`, `company`, `cycle_start`, `cycle_end`, `event_type`, `amount`
(signed), `balance_after`, `days`, `remarks`, `created_at`, `created_by`.
Event types: `PAYOUT`, `RENT`, `RENT_MISSED`, `RENT_RECOVERED` (new),
`DUES_CARRY`, `ADJUSTMENT`, `DEDUCTION_SWITCH`, `EV_SWAP`, `OPENING`.

**`balances`** — general rolling balance. `person_id` (PK), `current_balance`
(negative = dues), `last_updated`. EV arrears live separately in `ev_arrears`.

**`users`** — `email` (PK), `password_hash` (**bcrypt**), `role`
(admin / user), `is_active`, `created_at`.

**`status_tracking`** — `person_id` (PK), `status` (active / inactive),
`last_seen`, `ev_returned`.

---

## 6. Business rules

### 6.1 Rent calculation (handover-date proration)

Resolve: person → open EV assignment → `ev_unit` → `ev_model` → `weekly_rate`;
`daily_rate = weekly_rate ÷ 7`.

Chargeable days this cycle:
- No open assignment / no handover date → **full cycle** (current riders today).
- `handover_date < cycle_start` → full cycle.
- `cycle_start <= handover_date <= cycle_end` → `chargeable_days = (cycle_end − handover_date)`
  — **the handover day itself is not charged; the meter starts the next day.**
  This includes handover *on* `cycle_start` (charges 6 days of a 7-day cycle),
  so the engine and the daily ledger agree to the day.
- `handover_date > cycle_end` → 0.

Rent = `weekly_rate` if full standard (7-day) cycle, else `daily_rate × chargeable_days`.

**Continuity:** rent is billed from the day after `rent_charged_through`
(the last date billed) up to the cycle end, **clamped to the cycle**: a meter
behind `cycle_start` does *not* catch up (that reach-back caused the
stuck-meter double charges; backdated handovers are handled once by the manual
back-rent flow). Overlaps and re-runs never double-charge. The meter is
advanced per assignment leg, to `min(cycle_end, returned_date − 1)`, forward
only, and never for an EV handed over after the cycle.

### 6.2 Rent guard

Rent is charged at most once per person per cycle (checked against
`transactions` for an existing RENT this cycle). Handles multi-company riders
cleanly.

### 6.3 Missed rent & arrears

If an EV-holding person is absent from their deduction company's payout (so rent
can't be deducted), log `RENT_MISSED` and add it to `ev_arrears.outstanding`.
This is kept separate from general dues.

### 6.4 Recovery priority

When a payout arrives: **collect everything due, then release the rest.** Net the
payout against (this cycle's rent → outstanding EV arrears → general dues), in
that attribution order, floored at zero. Any uncovered remainder stays
outstanding and carries forward. Recovered arrears are logged as
`RENT_RECOVERED` and reduce `ev_arrears`.

### 6.5 Holds / COD

Two input styles, same outcome (mark rider HOLD, show pending amount, write to
`cod_holds`, list on the Hold List):
- **Jiffy / Spencer's** — separate COD sheet (found by its columns). Group by
  `WORKER CODE`, sum `AMOUNT` where `Transaction Status` = pending (the status
  column is picked up by name even when the config names none). Match worker
  code to the payout sheet's rider id — both are normalised the same way, so
  `'+91 98765 43210` on a hand-typed COD row still matches `9876543210`.
  `HUB CODE` and `WORKER NAME` are stored with each line (`cod_holds.hub_code`,
  `worker_name`); `cod_holds.hub` holds the hub *name* — the code resolved
  through `hub_codes`, a code → name map every payout file teaches from its
  own `store_ids` / `store_names` pairs (multi-store cells like
  "e005, s111" / "Marlin, Tolly DS" are paired up; latest file wins). A code
  no file has named yet stays as written.
- **Myntra** — inline `COD-Pending` column on the payout row.

The output's **HOLD sheet** has two blocks: COD riders who are in the payout
(their payout is held) and COD riders who are *not* in the payout — nothing to
hold, so the office chases them; each carries the hub the COD sheet gave.

COD is a withhold flag + recorded amount for manual decision; it is **not**
auto-deducted from the payout. (`Cod-Adjusted` / `Previous Week COD ADJ` are not
netted unless decided otherwise.)

### 6.6 Ledger / balances

`balance = prev_balance + payout − rent`. Positive → released and balance resets
to 0. Negative → nothing released, carried as dues. Dues + arrears never expire.

### 6.7 EV swaps

Changing a person's EV closes the open `ev_assignments` row (sets
`returned_date`) and opens a new one (new `ev_id`, new `handover_date`). Rate
follows the new unit's model automatically. Logged as `EV_SWAP`.

### 6.8 Cascading inactive logic (kept, now feeds arrears)

When the deduction anchor's rider ID disappears from a file: try another active
ID at the same company → else switch to another company the person is active in
→ else mark fully inactive. Whenever rent can't be collected this cycle, it
becomes `RENT_MISSED` → arrears (§6.3).

---

## 7. Identity & merge workflow

Aadhaar not collected yet, so identity is grouped by **name** at import, then
revised:
- **Same name, two people** — flagged by a duplicate report for review.
- **Same person, different names** (e.g. *Subhankar Das* / *Barui*) — name
  grouping creates two separate people; you merge them with the manual link tool.
  Merging reassigns rider IDs to one `person_id` and merges balances + arrears.
  Both names stay on record (each rider row keeps its own name).

A "review duplicates & aliases" pass runs right after roster import.
Aadhaar (`kyc_no`) will make this permanent later.

---

## 8. Payout file layouts

| Company   | Payout sheet                          | Rider-ID column | Payout column          | Hold |
|-----------|---------------------------------------|-----------------|------------------------|------|
| Dealshare | 2nd sheet `W## - Computation` (week # varies) | `rider_id` | `Final weekly payout`* | — |
| Blitz     | only sheet                            | `rider_id`      | `net_pay`              | — |
| Nykaa     | only sheet *(provisional: same as Blitz)* | `rider_id` (= Blitz ID) | `net_pay`      | — |
| Myntra    | 1st sheet                             | `Worker Code`   | `Final Payout`         | inline `COD-Pending` |
| Spencer's (Jiffy) — classic | 1st sheet (`WEEK1`…)      | `Rider id`      | `Total Payable Amount` | `COD` sheet (line items) |
| Spencer's — 2026-08 export | `Payout` sheet             | `rider_phone`   | `Total Payable`        | `COD HOLD` sheet (line items) |
| Zepto     | *to be provided*                      | —               | —                      | — |

\* Not `total payout to be released` — that figure includes Qwikserve's 3P cut.

**Jiffy hold sheet columns**: ORDER NUMBER, ORDER DATE, HUB CODE, Store Name, CH,
PAYMENT MODE, WORKER CODE, WORKER NAME, Vendor Name, AMOUNT, TIME, Transaction
Status, Transaction Type, Remarks. Sum `AMOUNT` per `WORKER CODE`.

**Parsing is config-driven** — a single generic parser reads each company's
`companies` row (sheet selector + columns + hold style), so onboarding a new
company is a config row, not code. This is what the dashboard's future parser
builder will sit on. A column config may list alternatives separated by `|`
(`Total Payable Amount|Total Payable`) so one row covers every layout a client
has shipped; the rider-id column additionally accepts `rider_id` / `Rider id` /
`Worker Code` / `rider_phone`, the name column `Name` / `Rider Name` /
`Worker Name`, and the hub column `Store` / `Hub` / `store_names` / `store_ids`.

**Hubs follow the file.** Every rider in a payout has their roster hub
(`rider_master.hub`) rewritten from the file's hub column on each run, and the
PAY/DUES rows show the file's hub. The roster value is only a fallback for
files with no hub column and for absent (INACTIVE) riders.

---

## 9. Initial upload files (database seed)

One workbook, three tabs, processed in order **Roster → EV Register → Opening
Balances**, with cross-tab reference checks and a dry-run preview before commit.
Re-uploading **skips riders that already exist** (only new riders are added);
identity, balances, and assignments are never overwritten by a re-import.
Column names are matched flexibly (case/spacing-insensitive, header-row
auto-detected), as with the payout files.

**Tab 1 — Roster** — one row per (rider_id, company); builds person_registry +
rider_master. Identity is grouped by `rider_name` until Aadhaar; the same person
under two names becomes two persons at import and is merged later via the link
tool (each rider row keeps its own name, so aliases are preserved).

| Column | Required | Notes |
|---|---|---|
| rider_id | yes | unique within a company |
| company | yes | one of the 5 known companies, else flagged |
| rider_name | yes | identity key; kept per-row so aliases survive a merge |
| hub | recommended | recruiter zones are organised by hub |
| vehicle | no | BIKE / EV / OTHER — informational only; rent comes from the EV Register |
| account_no | no | flagged if missing (needed to pay) |
| ifsc | no | flagged if missing |

**Tab 2 — EV Register** — builds ev_units + the opening ev_assignments. This is
where handover dates enter the system.

| Column | Required | Notes |
|---|---|---|
| ev_id | yes | physical EV id |
| provider | yes | Raft / Blive (must match the rate card) |
| model | yes | Regular / Blue / Standard (must match the rate card) |
| current_rider_name | no | blank = spare / unassigned; resolved to a person |
| company | yes if rider set | disambiguates the rider name |
| handover_date | no | blank → full-week rent; a date → prorate from the day after |

One open EV per person; a second open assignment is flagged as a conflict.

**Tab 3 — Opening Balances** — **include only riders who actually owe
something.** One row per person; seeds dues + EV arrears, applied once
(guarded), with OPENING audit rows. Builds balances + ev_arrears.

| Column | Required | Notes |
|---|---|---|
| rider_id | yes | any one of the person's ids |
| company | yes | disambiguates rider_id |
| opening_dues | no (0) | **positive = amount owed**; stored as a negative balance |
| opening_ev_arrears | no (0) | positive = EV back-rent owed |

---

## 10. Output workbook (per company, per cycle)

A styled `.xlsx`: frozen headers, INR formatting, colour-coded rows, totals, and
editable **Remarks** + **Manual Adjustment** columns. Sheets:

- **PAY** — riders with net release > 0 (lean view): Rider ID, Name, Hub,
  EV (id + model, if any), Gross Payout, Total Deductions, Net Release, COD Hold,
  Remarks (PAY/HOLD), Account No, IFSC, Manual Adjustment, Notes. HOLD riders
  (pending COD) stay here, flagged amber. The itemised rent/arrears/dues split
  lives in AUDIT.
- **DUES** — net-negative riders carried forward.
- **ARREARS** — strict missed-rent tab: per person, EV id+model, total missed,
  recovered to date, recovered this cycle, outstanding.
- **HOLD** — COD list: rider, COD total, source (Jiffy/Myntra); for Jiffy, the
  underlying line items.
- **INACTIVE** — in the DB but absent this cycle; flagged for dues / unreturned
  EV / missed rent.
- **AUDIT** — every transaction this cycle (incl. RENT_MISSED / RENT_RECOVERED).

The cycle overview/summary is deferred to the dashboard (Step 7), not the Excel.

---

## 11. Open items

- **Zepto** payout layout — pending a sample file.
- **Aadhaar (kyc_no)** — to be collected and backfilled later.
- ~~**Handover off-by-one**~~ — **resolved**: charge from the day *after*
  handover, including when handover lands on `cycle_start` (handover day free).
  Engine and daily ledger aligned; see §6.1.
- **Myntra COD** — confirm `COD-Pending` is the net figure (not netting
  `Cod-Adjusted`).
- **COD treatment** — currently a hold flag, not an auto-deduction.

---

## 12. Roadmap

1. ✅ Lock data model + file structures.
2. ✅ Restructure into a clean package; fix bugs; bcrypt; drop Spencers / add Blitz; lay down new schema.
3. ✅ Rework EV rent engine (handover proration, multi-provider/model rates).
4. ✅ Rework Hold/COD (Jiffy sheet + Myntra column).
5. ✅ Build missed-rent arrears + auto-recovery.
6. ✅ Build parsers for the 5 companies (config-driven).
7. ✅ Dashboard, payments reconciliation, provider bills, EV rent details.
8. Versioned migrations on both backends (`payout/db/migrations.py`) — done 2026-09.
9. Nykaa real file layout (provisional Blitz clone until a sample arrives).

---

## 13. Known issues being fixed in the rebuild

- Passwords stored as unsalted SHA-256 despite `bcrypt` in requirements → switch to bcrypt.
- `db_init.py check-duplicates` crashes (function defined after the `__main__` block).
- `admin.py list-companies` crashes (malformed f-string in the format spec).
