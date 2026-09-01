# Running the Payout System with Docker (PostgreSQL)

Two containers, started together by Docker Compose:

- **`db`** — PostgreSQL 16, data stored in the `payout_pg` Docker volume (on
  Docker's own Linux filesystem, **not** in this OneDrive folder).
- **`app`** — the API + built React frontend on **http://localhost:8000**, running
  as a non-root user with a healthcheck.

The app talks to Postgres via `PAYOUT_DB_URL`. (SQLite is still fully supported —
just unset `PAYOUT_DB_URL` — but the Docker setup uses Postgres.)

Prerequisite: **Docker Desktop** (Windows, WSL2 backend), running.

## One-time setup

**1. Secrets file** (`.env`, git-ignored):

```powershell
"PAYOUT_JWT_SECRET=$(python -c 'import secrets; print(secrets.token_hex(32))')" |
  Out-File -Encoding ascii .env
Add-Content .env "POSTGRES_PASSWORD=payout"
```

**2. Start just the database:**

```powershell
docker compose up -d db
```

**3. Migrate your existing SQLite data into Postgres.** First get a copy of your
real DB out of the old SQLite container (if it's still around) — otherwise use
your latest backup:

```powershell
docker cp payout:/data/payout.db "C:\payout_data\payout_pre_pg.db"   # if the old container exists
```

Install the Postgres driver into your venv and run the migrator (it creates the
schema, copies every table, and resets the id sequences):

```powershell
C:\payout_venv\Scripts\pip install "psycopg[binary]"
C:\payout_venv\Scripts\python scripts\migrate_sqlite_to_pg.py `
  "C:\payout_data\payout_pre_pg.db" `
  "postgresql://payout:payout@localhost:5432/payout"
```

It prints a row count per table — check they look right.

## Build & run

```powershell
docker compose up -d --build
```

Open **http://localhost:8000** and log in. Check health with `docker compose ps`
(both `db` and `app` should be `healthy`/`running`).

Because `PAYOUT_SEED_DEMO=0` is set for the app, no demo login or demo data is
created — you'll see only your real, migrated data.

## Everyday commands

```powershell
docker compose up -d              # start both (after a reboot etc.)
docker compose ps                 # status + health
docker compose logs -f app        # watch backend logs
docker compose logs -f db         # watch Postgres logs
docker compose down               # stop (the payout_pg volume/data persists)
docker compose up -d --build      # rebuild after a code change
```

With `restart: unless-stopped`, both containers come back automatically when
Docker Desktop starts, so day-to-day you just open the browser.

## Back up the database

`pg_dump` into a file under `C:\payout_data\` — a local, non-synced directory.
Dumps contain real rider data (Aadhaar, bank details); never keep them inside
OneDrive or inside this repository folder:

```powershell
docker exec payout-db pg_dump -U payout -d payout `
  > "C:\payout_data\payout_pg_backup_$(Get-Date -Format yyyyMMdd_HHmm).sql"
```

Restore into a fresh db with `psql`:

```powershell
Get-Content backup.sql | docker exec -i payout-db psql -U payout -d payout
```

## Notes

- The app's SQL is written in SQLite dialect and translated to PostgreSQL at the
  connection layer (`src/payout/db/connection.py`) when `PAYOUT_DB_URL` is set.
  The full test suite passes on **both** backends.
- Want to go back to SQLite temporarily? Unset `PAYOUT_DB_URL` and set
  `PAYOUT_DB=/data/payout.db`. Nothing else changes.
