# Working on this repo (humans and AI assistants)

## Commands
- Backend: `pip install -e ".[dev,api]"` · `pytest` (SQLite, coverage floor) ·
  `PAYOUT_DB_URL=postgresql://payout:payout@localhost:5432/payout_test pytest --no-cov` ·
  `ruff check src tests && ruff format --check src tests` · `mypy src` (advisory)
- Frontend (`frontend/`): `npm ci` · `npm run typecheck` · `npm run lint` · `npm test` · `npm run build`
- Dev servers: `.\start.ps1` (Windows) or `payout-api --reload` + `npm run dev`.
- Pre-commit: `pip install pre-commit && pre-commit install` (ruff, gitleaks, data-file guard).

## Invariants — do not break
- **Money is integer paise everywhere inside** (`payout/money.py`). Rupees exist only at the
  API edge (`RupeeizeMiddleware` + `MONEY_KEYS`) and in Excel output (`money_cols`).
  Any new money field in a JSON response must be added to `MONEY_KEYS`; any rupee input from
  a client goes through `to_paise()` before it touches the ledger.
- **SQL is written in SQLite dialect** with `?` placeholders and translated to Postgres at
  execution time (`payout/db/connection.py`). No `%s`, no f-string values, no dialect-specific
  functions without checking the translator. Both backends must pass the suite (CI runs both).
- **Schema changes go in `payout/db/migrations.py`** (append a numbered step, keep it
  idempotent) AND in `schema.py` (for fresh databases). Never `ALTER TABLE` anywhere else.
- **The ledger is append-only.** Corrections are new offsetting rows, never edits.
- **The rent meter (`rent_charged_through`) only moves forward, per assignment**, via
  `advance_rent_charged_through`. A cycle bills its own days **plus** any contiguous run
  of days behind the meter that nothing ever billed (`rent.unbilled_gap`; the 2026-09-04
  Jeet Ghosh fix — days between two companies' cycles used to be written off). A day is
  "accounted" when the day-ledger says so or a rent row's billed window covers it
  (`rent._day_accounted`). A backdated handover with no meter still does not reach back:
  that is the back-rent flow. `payout-manage unbilled-days [--apply]` sweeps old gaps.
- Every route that writes uses `require_admin` / `require_creator`. Tests enforce that
  anonymous callers get 401 on every mutating route.
- **Roles: creator > admin > recruiter > user** (`api/auth.py`). Roster/fleet writes take
  `require_recruiter`; money-side routers are mounted with `no_recruiter`; money-changing
  writes stay `require_admin`. Every recruiter-reachable write calls
  `domain/activity.record_activity` in the same transaction — that log is how admins review
  field staff. The API surface is documented in `docs/RECRUITER_API.md`; keep it current.
- **The creator tier is invisible below creator.** Non-creators see creators as `admin`
  (`users.visible_role`), creator-only refusals say just "Not permitted", `/docs` and
  `/openapi.json` are creator-only, and the SPA never renders the word for anyone else.
  Keep it that way when adding routes or UI.
- **Placeholder rider ids (`QSPEND<NNNN>`) are temporary.** Tagging a real id to that
  person at that company retires the placeholder (`domain/placeholders.py`); any path
  that attaches a rider id to an existing person must go through it.
- Tables that reference a person or EV are listed in `payout/db/references.py`; use its
  helpers for deletes/merges and keep it in step with `schema.py` (a test checks).

## Never
- `git add -f`, or commit anything under `data/`, `*.sql`, `*.db*`, `*.xlsx`, `*.zip`.
  Real rider data (Aadhaar, bank details) lives in `C:\payout_data\`, off OneDrive.
- Run fix scripts against production without `--dry-run` first and a `pg_dump`.
- Point `PAYOUT_DB` / `PAYOUT_DB_URL` at a real database when running tests
  (conftest refuses non-`_test` Postgres names and always uses a temp SQLite file).
- Set `PAYOUT_SEED_DEMO=1` anywhere but the public demo.

## Where things are
- Domain engine: `src/payout/domain/` (engine.py orchestrates a cycle; rent.py, arrears.py,
  holds.py are the rules). Parsers: `src/payout/parsers/` (config-driven from `companies`).
- API: `src/payout/api/routes/*.py`. Auth: `api/auth.py`, `api/config.py`.
- Frontend: `frontend/src` — `api/client.ts` is the only place that calls `fetch`;
  `hooks/useApi.ts` for reads; `lib/dates.ts` / `lib/format.ts` for dates and money.
- Design spec: `DESIGN.md`. Deployment: `DOCKER.md`, `docker-compose.yml`, `render.yaml`.
