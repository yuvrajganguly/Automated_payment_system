# Running the Payout System with Docker

One container serves both the API and the built frontend on **http://localhost:8000**.
The database lives in a Docker volume (`payout_data`) on Docker's own Linux
filesystem — **not** in this OneDrive folder — so it can't be corrupted by sync.

Prerequisite: **Docker Desktop** (Windows, WSL2 backend).

## First-time setup — import your existing DB

Do this once, so the container starts with your real data instead of a demo seed:

```powershell
docker volume create payout_data
docker run --rm -v payout_data:/data -v C:/payout_data:/src alpine `
  sh -c "cp /src/payout.db /data/payout.db; rm -f /data/payout.db-wal /data/payout.db-shm"
```

(That copies `C:\payout_data\payout.db` into the volume and clears any stale WAL.)

## Build & run

```powershell
docker compose up -d --build
```

Open **http://localhost:8000** and log in (`yuvrajganguly29@gmail.com`).
No ports to free, no venv, no PAYOUT_DB to set — it's all inside the container.

## Everyday commands

```powershell
docker compose logs -f app      # watch backend logs
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

## Notes

- Change `PAYOUT_JWT_SECRET` in `docker-compose.yml` to a long random string.
- Code changes require a rebuild (`docker compose up -d --build`); for rapid
  frontend/backend iteration you can still run the local dev servers instead.
