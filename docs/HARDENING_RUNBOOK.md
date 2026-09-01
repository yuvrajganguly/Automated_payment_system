# Hardening runbook — 2026-09-01

What the `review/hardening` branch changes, what it needs from the operator
before/after deploy, and how to apply it. Read top to bottom once.

## 1. Apply the branch (on the dev machine)

The branch arrives as a git bundle so nothing touches your working tree until
you check it out.

```powershell
cd C:\Users\Yuvraj\OneDrive\Documents\Automated_payment_system
git fetch _to_delete\payout-hardening.bundle review/hardening:review/hardening
git switch review/hardening        # rewrites the 16 CRLF files to LF — that IS the fix
npm --prefix frontend ci
pip install -e ".[dev,api]"
pytest                             # 104 tests, both suites pass on SQLite and Postgres
```

Then open a PR `review/hardening → master` so CI runs both backends, or merge
locally. The ten commits are independent enough to review one at a time.

If `git` complains about `.git/index.lock`: it could not be removed from the
sandbox because of OneDrive's file lock — delete it by hand
(`del .git\index.lock`) with no git process running. Also delete the 63
`.git/objects/*/tmp_obj_*` leftovers: `git prune` handles them.

## 2. Before the first start — environment

The app now **refuses to start without a JWT secret of ≥ 32 characters**.

```powershell
python -c "import secrets; print(secrets.token_hex(32))"   # paste into .env as PAYOUT_JWT_SECRET
```

Rotate the secret even if one exists: `admin@demo.com` has a live session on
production until its token expires (12 h), and rotating invalidates it now.

| Variable | Production (docker-compose) | Render demo | Local dev |
|---|---|---|---|
| `PAYOUT_JWT_SECRET` | required, ≥ 32 chars | generated | optional if `PAYOUT_ALLOW_DEV_SECRET=1` |
| `PAYOUT_SEED_DEMO` | unset / `0` (**default is now off**) | `1` (already in render.yaml) | `0` (start.ps1 sets it) |
| `PAYOUT_DEV_PRINT_EMAIL` | never | never | `1` if you want reset codes on the console |
| `PAYOUT_SMTP_*` | set, or "forgot password" answers 503 | — | — |

## 3. Production database — run once, in this order

Take a dump first: `docker exec payout-db pg_dump -U payout -d payout > C:\payout_data\pre_hardening_$(Get-Date -Format yyyyMMdd).sql`

```sql
-- 3a. The demo admin is in prod (pg_data_w28.sql: 1 users row, 21 audit rows, 3 transactions).
SELECT email, role, is_active FROM users WHERE email LIKE '%@demo.com';
DELETE FROM users WHERE email IN ('admin@demo.com', 'viewer@demo.com');
-- Review what that account did before deciding whether its 3 transactions stand:
SELECT id, person_id, event_type, amount, created_at FROM transactions WHERE created_by = 'admin@demo.com';

-- 3b. Login bodies (plaintext passwords) were stored in audit_log. Purge them.
UPDATE audit_log SET body_excerpt = NULL WHERE path LIKE '/api/auth/%';
-- Every password used on prod before this deploy should be treated as exposed:
-- ask each user to change it (Settings → Change password) or reset with
--   payout-admin reset-password --email <e>

-- 3c. payment_lines.amount was stored in RUPEES before this deploy (parser bug).
-- Rows from uploads before the deploy need ×100. Check first:
SELECT u.id, u.file_name, u.uploaded_at, MIN(l.amount), MAX(l.amount)
FROM payment_uploads u JOIN payment_lines l ON l.upload_id = u.id
GROUP BY u.id ORDER BY u.id;
-- If those look like rupees (hundreds/thousands, not hundreds of thousands):
UPDATE payment_lines SET amount = amount * 100
WHERE upload_id IN (SELECT id FROM payment_uploads WHERE uploaded_at < '<deploy timestamp>');
```

The schema migration itself is automatic: on first start the app creates
`schema_migrations`, stamps `0001_baseline`, and applies
`0002_reset_token_attempts` and `0003_companies_shared_rider_ids` (you will
see `[startup] applied migrations: …` in the log). The Nykaa company row is
inserted by the seed on the same start.

## 4. Files — get real data out of the synced repo folder

Move to `C:\payout_data\` (already off OneDrive): `pg_data5.sql`,
`pg_data_w28.sql`, `payout_db_backup_encrypted.zip`, everything under
`data\private\`, `data\Payout_Seed_Workbook*.xlsx`, `scripts\build_seed.py`.
Then `git status` should show nothing untracked that looks like data (the new
`.gitignore` covers these by extension, but the point is that OneDrive no
longer syncs them).

Delete `_to_delete\` (contains the review tarballs and the bundle once fetched).

One-time history check, for the record (it was clean when I ran it):
`git log --all --name-only --pretty=format: -- '*.xlsx' '*.db' '*.sql' '*.zip'`

## 5. Nykaa

- Company row: layout cloned from Blitz (`rider_id` / `net_pay` / `total_del`,
  no COD). When the real file arrives:
  `payout-admin update-company --name Nykaa --rider-col "<header>" --payout-col "<header>" --payout-sheet 0`
- `rider_ids_shared_with = Blitz`: a Nykaa file's unknown rider id that exists
  under Blitz is linked to that person automatically; the preview lists them
  under "linked from Blitz by shared rider ID". Ids unknown at both companies
  still go through the normal onboarding modal.
- To turn the auto-link off: `payout-admin update-company --name Nykaa --shares-rider-ids-with ""`.

## 6. Behaviour changes operators will notice

- **Commit & Download** is disabled until a preview of that exact file + dates
  has run, and asks for confirmation with the totals.
- A file with a **repeated rider id** is rejected with the ids listed. A
  payout cell that is **not a number** keeps the rider present (no missed-rent
  arrears) and blocks commit until fixed; a **blank** payout is treated as 0.
- **Re-committing** a cycle returns 409 unless `force`; a forced re-run
  replaces the cycle's COD holds instead of doubling them.
- **Forgot password** returns "not set up on this server" until SMTP is
  configured; five wrong codes lock the code; login is rate-limited
  (20/min per IP).
- Deactivating a user logs them out on their next request instead of in ≤ 12 h.
- The demo login button only appears when the server is in demo mode.
- Dashboard export sheets and the "Owed to providers" drawer now show rupees
  (they showed paise).

## 7. Still open (not in this branch)

- mypy is still advisory (30 errors); make it gate once fixed.
- Python lockfile (`uv lock`) + non-editable install in the Dockerfile.
- Turn the `scripts/find_*` detectors into `domain/invariants.py` + a nightly check.
- Frontend: extract shared table/form/modal components; replace the remaining
  `confirm()` dialogs; `openapi-typescript` for `api/types.ts`.
- A compose `backup` service writing encrypted `pg_dump`s to `C:\payout_data\backups`.
