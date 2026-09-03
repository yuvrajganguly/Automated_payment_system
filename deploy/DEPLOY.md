# Deploying the real system to a Hetzner VPS

The production stack is `deploy/docker-compose.prod.yml`: Caddy terminates
HTTPS (automatic Let's Encrypt via an sslip.io hostname — no domain needed),
the app and Postgres run on an internal network with nothing else exposed, and
a sidecar takes nightly dumps into `deploy/backups/`.

Sizing: a CX22 (2 vCPU / 4 GB, ~€3.79/mo) is comfortable for this workload,
including the coming team app (12–20 users hitting the same API). It can be
resized in place later.

---

## 0. Before anything: get the code onto GitHub

The server pulls from GitHub, so the branch must be pushed first. On your
machine:

```powershell
git push -u origin review/hardening
# optionally merge to master once you're happy:
#   git checkout master ; git merge review/hardening ; git push
```

## 1. Create the server (one time, ~5 minutes)

1. Sign up / log in at https://console.hetzner.cloud → New project → Add server.
2. Location: **Falkenstein or Nuremberg** (fine latency from India; Singapore
   is offered at a small surcharge if you prefer).
3. Image: **Ubuntu 24.04**. Type: **CX22** (2 vCPU / 4 GB).
4. **SSH key**: paste your public key. No key yet? In PowerShell:
   `ssh-keygen -t ed25519` (accept defaults), then paste the contents of
   `C:\Users\Yuvraj\.ssh\id_ed25519.pub`.
5. Create. Note the server's IP — call it `SERVER_IP` everywhere below.

## 2. Prepare the server

```powershell
ssh root@SERVER_IP
```

```bash
git clone https://github.com/yuvrajganguly/Automated_payment_system.git payout
cd payout && git checkout review/hardening
bash deploy/setup-server.sh          # firewall, docker, auto-updates
```

## 3. Configure

```bash
cd ~/payout/deploy
cp .env.prod.example .env
openssl rand -hex 24                 # -> POSTGRES_PASSWORD
openssl rand -hex 32                 # -> PAYOUT_JWT_SECRET
nano .env                            # paste both; set SITE_ADDRESS
```

`SITE_ADDRESS` with no domain: take the server IP, replace dots with dashes:
server `203.0.113.10` → `SITE_ADDRESS=payout.203-0-113-10.sslip.io`.

## 4. First boot

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps        # all healthy?
```

Open `https://payout.<ip-with-dashes>.sslip.io` — certificate should be valid
automatically. The database is empty at this point; don't create users yet if
you're migrating (step 5 brings your real users along).

## 5. Migrate the data up from your local Docker

On your machine (PowerShell):

```powershell
docker exec payout-db pg_dump -U payout -Fc payout -f /tmp/payout.dump
docker cp payout-db:/tmp/payout.dump .\payout.dump
scp .\payout.dump root@SERVER_IP:/root/payout/deploy/
```

On the server:

```bash
cd ~/payout/deploy
sh restore.sh payout.dump            # type RESTORE when asked
docker compose -f docker-compose.prod.yml restart app
```

Verify: log in with your REAL admin account at the sslip.io URL and compare
the dashboard totals against your local instance. Same numbers = migration
done. From this moment the cloud is the single source of truth — keep the
local Docker copy as an offline backup, stop entering data there.

## 6. Lock it down (do not skip)

```bash
# Disable the old public demo login if it exists in the migrated data:
docker compose -f docker-compose.prod.yml exec db \
  psql -U payout -d payout -c \
  "UPDATE users SET is_active=0 WHERE email='admin@demo.com';"
```

Then in the app: Admin → change your own admin password to something strong
and unique. Every future team member of the 12–20 app users gets their OWN
account with the least role that works (viewer/creator, not admin) — never a
shared login.

## 7. Updating the deployment later

```bash
cd ~/payout && git pull
cd deploy && docker compose -f docker-compose.prod.yml up -d --build
```

## 8. Backups

- Nightly `pg_dump` lands in `~/payout/deploy/backups/`, 14 days kept.
- **Off-server copy** (a server can die): from your machine, weekly or via
  Task Scheduler:
  `scp root@SERVER_IP:payout/deploy/backups/$(date +payout-%Y%m%d)*.dump .\`
  (or simply grab the newest file).
- Restore drill: `sh restore.sh backups/<file>.dump` — practice once on day
  one so it's boring on the bad day.

## Notes for the coming team app

- The app must call the API over HTTPS at the SITE_ADDRESS URL — never the
  database directly.
- If the app is served from a different origin, set `PAYOUT_CORS_ORIGINS` in
  `deploy/.env` and `up -d` again.
- Auth: each user logs in with their own account; the JWT cookie/bearer flow
  the web UI uses works for the app too.
