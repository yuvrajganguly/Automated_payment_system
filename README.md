# Payout Management System

![CI](https://github.com/yuvrajganguly/Automated_payment_system/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178c6)
![License](https://img.shields.io/badge/license-MIT-green)

Automated weekly rider payouts for an Indian gig-delivery ops business. The
tool parses each company's payout Excel, applies EV rent (with handover-date
proration, per-EV maintenance windows, and manual waivers), settles outstanding
general dues and EV-rent arrears, applies COD holds from line-item or column
sources, and produces a styled instruction workbook — all behind a typed REST
API and a React UI.

---

## What problem does it solve

An operator runs riders across **six delivery companies** (Dealshare, Myntra,
Jiffy, Zepto, Blitz, Nykaa). Each week brings separate Excel files of "what we
owe each rider", but the rider population overlaps (one human can have several
rider IDs across companies — Nykaa even reuses Blitz's IDs, which the engine
links automatically), many riders rent EVs at three different weekly
rates, EV rent has to be deducted from whichever company's payout will be
processed first, some riders have pending **Cash-on-Delivery** that should
freeze their payout, and some riders simply disappear from a company's file
for a week — that rent then becomes "missed" arrears to be clawed back later.

Doing this in Excel by hand is slow and error-prone. Small mistakes — a missed
deduction, a forgotten hold, a typo in a cycle date — cost real money. This
tool models the domain precisely and automates the whole loop: **upload →
preview → commit → download**.

## Highlights

### Continuous EV rent metering
Every EV assignment carries a `rent_charged_through` marker. Each cycle bills
from the day **after** it up to the cycle end, clamped to the cycle itself —
**overlaps and re-runs never double-charge, and a behind meter never reaches
back** (backdated handovers are settled once via the back-rent flow). The meter
advances per assignment, forward only, whether a day was actually charged
(rider present) or missed to arrears (rider absent), so every day an EV is
held is accounted for exactly once.

### Config-driven parsers
The five payout files have wildly different shapes — Dealshare's payout sits
on a sheet whose name changes weekly (`W21 - Computation`, `W22 - Computation`,
…), Jiffy ships CoD holds as a separate sheet of order line items, Myntra
ships them inline as a `COD-Pending` column. **One config-driven generic
parser handles all of it** — sheet pattern matching, header-row
auto-detection, currency-symbol stripping, tolerant column matching.
Onboarding a new company is a single database row, no code.

### "Collect everything due, then release the rest"
A pure, exhaustively tested settlement function takes a rider's gross payout,
current rent, previous balance and outstanding arrears, then:
1. pays this cycle's rent,
2. recovers outstanding EV-rent arrears,
3. clears general dues,
4. releases whatever remains.

Arrears get priority over general dues, so EV back-rent never loses out.

### Manual overrides everywhere, fully audited
Operators can intervene at every step without breaking the audit trail:
EV maintenance windows (auto-excluded from rent), per-cycle day waivers, full
cycle waivers, rate overrides, ledger credits/debits with mandatory reasons,
force-hold and force-release. **Every intervention becomes an immutable
`ADJUSTMENT` / `RENT_MISSED` / `RENT_RECOVERED` / `DEDUCTION_SWITCH`
transaction.** The database is append-only by design — corrections happen as
new offsetting rows, never edits.

## Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌───────────────────┐
│ React + Vite +  │ ─► │  FastAPI        │ ─► │ Python domain     │
│ TypeScript      │JWT │  /api routes    │    │ engine (rent,     │
│ Tailwind        │    │ payout/api/     │    │ arrears, holds,   │
│ (frontend/)     │    └────────┬────────┘    │ settlement)       │
└─────────────────┘             │             └────────┬──────────┘
                                ▼                      ▼
                       ┌─────────────────┐    ┌─────────────────┐
                       │ openpyxl xlsx   │    │ PostgreSQL 16   │
                       │ output builder  │    │ (SQLite in dev) │
                       └─────────────────┘    └─────────────────┘
```

The domain layer is **pure** — `chargeable_days`, `rent_for_days`,
`apply_settlement`, `compute_holds` take primitives and return primitives.
They don't know about HTTP, files, or the database. That's what makes them
exhaustively testable and keeps the system reasonable to evolve.

**Dual database backends.** Production runs **Dockerized PostgreSQL 16**
(`docker compose up`, see [DOCKER.md](./DOCKER.md)); development and tests
default to a zero-setup SQLite file. All application SQL is written once in
SQLite dialect and translated to Postgres at execution time by a single
translation layer (`src/payout/db/connection.py`) — set `PAYOUT_DB_URL` to a
Postgres URL and nothing else in the app needs to change. A one-shot migrator
(`scripts/migrate_sqlite_to_pg.py`) moves existing SQLite data over.

## Output workbook

`process_cycle` produces a 6-sheet styled `.xlsx`:

| Sheet     | What it shows |
|-----------|---------------|
| **PAY**       | Riders releasing money this cycle. Lean view: Person ID, Rider ID, Vehicle, EV ID, **Rent Charged**, Gross Payout, Previous Dues, Total Deductions, Net Release, Carry Forward, COD Hold, Remarks (PAY/HOLD), bank details, editable Manual Adjustment + Notes columns. HOLD rows flagged amber. |
| **DUES**      | Net-negative riders carrying forward. |
| **ARREARS**   | Per person: total missed, total recovered, recovered this cycle, outstanding. |
| **HOLD**      | Per-rider COD totals + (for Jiffy) the underlying line items. |
| **INACTIVE**  | EV holders absent this cycle, flagged for missed rent / dues / unreturned EV. |
| **AUDIT**     | Every transaction this cycle, colour-coded by event type. |

(An anonymised sample workbook for `data/sample/` is on the to-do list; real
data never lives in this repository — see `.gitignore`.)

## Tech stack

| Layer       | Stack |
|-------------|-------|
| Frontend    | React 18 · TypeScript 5 · Vite 5 · Tailwind 3 · React Router 6 |
| Backend     | Python 3.10+ · FastAPI 0.110 · Pydantic 2 · python-jose (JWT, httpOnly cookie) · bcrypt · psycopg 3 |
| Persistence | PostgreSQL 16 (Dockerized) in production · SQLite (WAL) for dev/tests · idempotent schema, FKs |
| Files       | pandas + openpyxl (Excel I/O) |
| CLIs        | `payout-manage` (DB + import) · `payout-admin` (users/companies) · `payout-api` (uvicorn) |
| Quality     | pytest + pytest-cov · ruff · black · mypy |
| CI          | GitHub Actions: lint + typecheck + tests on SQLite **and** PostgreSQL + frontend build |

## Quick start

**Docker (production-style, PostgreSQL):**

```bash
cp .env.example .env      # set a strong PAYOUT_JWT_SECRET (required, >= 32 chars)
docker compose up -d --build
# app on http://localhost:8000 — see DOCKER.md for migration + daily commands
```

**Local development (SQLite, hot reload):**

```bash
# Python 3.10+, Node 20+, pip + npm
git clone https://github.com/yuvrajganguly/Automated_payment_system.git
cd Automated_payment_system

# install the backend with the API extras
pip install -e ".[api]"

# initialise the database and create an admin user
# a JWT secret is required (>= 32 chars); for a throwaway local run you may
# instead set PAYOUT_ALLOW_DEV_SECRET=1
cp .env.example .env
payout-manage init --email you@example.com --password ChangeMe12

# (optional) load a seed workbook (Roster / EV Register / Opening Balances)
payout-manage seed onboarding.xlsx --commit

# start the API
payout-api --reload                    # http://127.0.0.1:8000
```

In a second terminal:

```bash
cd frontend
npm install
npm run dev                            # http://localhost:5173
```

Then open `http://localhost:5173`, log in, upload a Jiffy/Dealshare/Myntra/Blitz/Nykaa
payout file, preview the dry run, and commit to download the styled workbook.
Interactive API docs live at <http://127.0.0.1:8000/docs>.

## Project structure

```
.
├── DESIGN.md                     ← full design specification
├── DOCKER.md                     ← Dockerized PostgreSQL: setup + migration
├── README.md                     ← (you are here)
├── pyproject.toml                ← project metadata, deps, tooling config
├── data/sample/                  ← anonymised sample workbooks
├── tests/                        ← pytest suite (rent/holds/arrears/overrides)
├── .github/workflows/ci.yml      ← GitHub Actions: lint + types + tests + build
├── src/payout/                   ← Python package
│   ├── api/                      ← FastAPI app + 16 route modules
│   ├── cli/                      ← payout-manage / payout-admin / payout-api
│   ├── db/                       ← schema + versioned migrations + seeds + dual-backend connection
│   ├── domain/                   ← pure-Python engine
│   │   ├── engine.py             ← process_cycle orchestrator
│   │   ├── rent.py               ← handover proration + continuity meter
│   │   ├── arrears.py            ← apply_settlement + missed-rent ledger
│   │   ├── holds.py              ← Jiffy + Myntra hold rules
│   │   └── adjustments.py        ← manual ledger + EV maintenance
│   ├── parsers/                  ← config-driven Excel parsers
│   ├── ingest/                   ← seed workbook importer
│   ├── auth/                     ← bcrypt password hashing
│   └── output.py                 ← 6-sheet styled .xlsx builder
└── frontend/                     ← React SPA
    └── src/
        ├── api/                  ← typed fetch client + types
        ├── auth/                 ← JWT context + ProtectedRoute
        ├── pages/                ← Login · Process Payout · Riders · Person
        │                            EVs · Arrears · Settings
        └── components/           ← Layout + Sidebar + Spinner
```

## Tests

```bash
pip install -e ".[dev,api]"
pytest -v
```

The pure-functional domain layer has thorough parametrised tests covering
boundary cases (handover on cycle start vs. mid vs. end, partial weeks,
maintenance overlap with chargeable window, arrears priority over general
dues, the rent meter catching gaps and rejecting overlaps). A disposable-DB
fixture in `tests/conftest.py` re-initialises a fresh database per test for
the DB-backed cases — SQLite by default, or PostgreSQL when `PAYOUT_DB_URL`
is set, so the exact same suite exercises both backends (CI runs both).

## Design documentation

[`DESIGN.md`](./DESIGN.md) is the deep spec: every table in the data model,
business rules (rent, arrears recovery, hold styles, recovery priority,
continuity, manual overrides), payout file layouts for the five companies,
the seed workbook format, the roadmap, and known issues.

## License

MIT — see [LICENSE](./LICENSE).
