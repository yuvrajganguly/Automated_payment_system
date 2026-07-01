# Running the Payout System with Docker

One production container serves both the API and the built frontend on
**http://localhost:8000**. It runs as a **non-root** user, has a **healthcheck**,
and stores the database in a Docker volume (`payout_data`) on Docker's own
Linux filesystem — **not** in this OneDrive folder — so it can't be corrupted
by sync.

Prerequisite: **Docker Desktop** (Windows, WSL2 backend).

## One-time setup

**1. Create the secrets file** (`.env`, git-ignored) with a strong random key:

```powershell
"PAYOUT_JWT_SECRET=$(python -c 'import secrets; print(secrets.token_hex(32))')" |
  Out-File -Encoding ascii .env
```

**2. Import your existing DB** into the volume, so the app starts with real data
instead of a demo seed:

```powershell
docker volume create payout_data
docker run --rm -v payout_data:/data -v C:/payout_data:/src alpine `
  sh -c "cp /src/payout.db /data/payout.db; rm -f /data/payout.db-wal /data/payout.db-shm"
```

## Build & run

```powershell
docker compose up -d --build
```

Open **http://localhost:8000** and log in (`yuvrajganguly29@gmail.com`).
Check health / status with `docker compose ps` (shows `healthy`).

## Everyday commands

```powershell
docker compose logs -f app      # watch backend logs
docker compose ps               # status + health
docker compose restart app      # restart
docker compose down             # stop (the volume/data persists)
docker compose up -d --build    # rebuild after a code change
```

## Back up the database

```powershell
docker cp payout:/data/payout.db "C:\payout_data\payout_backup_$(Get-Date -Format yyyyMMdd_HHmm).db"
```

A static copy like this is safe to keep in OneDrive; only the live, being-written
DB must stay out of synced folders — and here it does, inside the volume.
