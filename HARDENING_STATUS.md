# Hardening branch — status (2026-09-01)

Branch `review/hardening` (11 commits on top of `7ee00a6`) is fetched into the repo on
"prometheus" and also saved as `_to_delete/payout-hardening.bundle`. Working tree untouched;
`git switch review/hardening` to take it. Runbook: `HARDENING_RUNBOOK.md` (repo root; also
`docs/HARDENING_RUNBOOK.md` on the branch).

## Verified
- 104 pytest tests pass on SQLite AND PostgreSQL 16 (was 64; smoke test now asserts 200).
- ruff + ruff-format clean and gating in CI (98 historical findings baselined with noqa);
  coverage floor 55% (actual 56.5%); mypy still advisory (30 errors).
- Frontend: tsc clean, eslint 0 errors, 9 vitest tests, vite build 183 kB initial (was 375 kB).

## What the branch does (by commit)
1. chore: `.gitattributes` text=auto eol=lf (ends CRLF churn), gitignore by shape, pre-commit
   (ruff, gitleaks, data-file guard), tsconfig.node noEmit, DOCKER.md no OneDrive backups.
2. security: run_cycle requires admin; audit log never stores /api/auth bodies (+form scrub);
   demo seed opt-in + refuses with real users; JWT secret ≥32 chars required
   (PAYOUT_ALLOW_DEV_SECRET=1 for dev); per-request is_active/role lookup; OTP lock after 5,
   rate limits on auth routes; forgot-password 503 without SMTP; migrations runner
   (db/migrations.py, schema_migrations on both backends); safe conftest (temp SQLite, PG must be *_test).
3. engine: leg-scoped forward-only rent meter; duplicate rider ids rejected; junk payout cells
   keep rider present + block commit; blank = 0; post_adjustment/importer upsert; re-commit guard
   inside the transaction (409); forced re-run replaces cod_holds; **Nykaa** company
   (Blitz layout, provisional) with rider_ids_shared_with=Blitz auto-link.
4. money: to_paise in cod.py + bank_mis; exports.add_styled_sheet honours money_cols;
   MONEY_KEYS += owed, held, collected_current, rolled_*; bank_mis header alias collision fixed.
5. db: references.py canonical FK lists; creator deletes/merges use them; test asserts vs schema.
6. nykaa: API/CLI expose rider_ids_shared_with; DESIGN.md/README updated.
7. ci: gating, permissions, concurrency, payout_test DB, pip-audit, docker build job, dependabot.
8. frontend: api.patch/download, useApi (AbortController), lib/dates (local time, IST tests),
   lib/format (en-IN), commit-requires-preview + confirm, unreadable/auto-linked riders shown,
   demo button gated on /api/health, safe localStorage parse, lazy routes, ESLint+Vitest.
9. docs: AGENTS.md. 10. creator system stats/backup work on PG. 11. runbook.

## Operator must do (runbook §2–§4)
- Set PAYOUT_JWT_SECRET (≥32 chars) and rotate it; delete admin@demo.com/viewer@demo.com from
  prod; purge audit_log body_excerpt for /api/auth/%; ask users to change passwords;
  backfill payment_lines.amount ×100 for pre-deploy uploads (check first);
  move real-data files to C:\payout_data\; delete _to_delete\.

## Still open
mypy gating; uv lock + non-editable Docker install; invariants module from scripts/find_*;
frontend component extraction + remaining confirm() dialogs + openapi-typescript;
compose backup service; real Nykaa file layout.
