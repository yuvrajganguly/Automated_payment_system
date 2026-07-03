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
(b