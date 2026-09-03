# Deploying the real system to AWS Lightsail (Mumbai)

The production stack is `deploy/docker-compose.prod.yml`: Caddy terminates
HTTPS (automatic Let's Encrypt), the app and Postgres run on an internal
network with nothing else exposed, and a sidecar takes nightly dumps into
`deploy/backups/`. Lightsail disks are encrypted at rest by default.

Sizing: the **Small plan — $12/mo, 2 vCPU / 2 GB / 60 GB SSD** — carries this
workload including the coming 12–20-user team app. Mumbai (`ap-south-1`)
includes 1.5 TB transfer/month, which is ~100× what this system uses. If the
first `docker compose build` feels tight on 2 GB, add swap (step 2) rather
than upsizing.

---

## 0. Before anything: get the code onto GitHub

The server pulls from GitHub, so the branch must be pushed first. On your
machine:

```powershell
git push -u origin review/hardening
```

## 1. AWS account basics (one time — do these before any server exists)

1. Sign in at https://console.aws.amazon.com (root user).
2. **Turn on MFA for the root user** (Security credentials → MFA). A leaked
   AWS password without MFA ends with someone else's crypto miner and your
   bill.
3. Create **no access keys**. This deployment never needs them; keys lying
   around are the #1 AWS breach cause.
4. Billing console → Budgets → create a budget alert at ~$15/mo so a surprise
   can't run for weeks.

## 2. Create the instance (~5 minutes)

1. https://lightsail.aws.amazon.com → Create instance.
2. Region: **Mumbai (ap-south-1)** — rider data stays in India.
3. Image: **OS only → Ubuntu 24.04 LTS**. Plan: **$12 Small (2 GB)**.
4. SSH key: download the default key, or upload your own
   (`ssh-keygen -t ed25519` in PowerShell, then paste
   `C:\Users\Yuvraj\.ssh\id_ed25519.pub` under "Upload key").
5. Create, then on the instance's **Networking** tab:
   - Attach a **static IP** (free while attached) — call it `SERVER_IP`.
   - Firewall: keep SSH(22) + HTTP(80), **add HTTPS(443)**.
   - Optional but good: restrict SSH(22) to your own IP.

```powershell
ssh -i <path-to-key> ubuntu@SERVER_IP
```

```bash
sudo -i
git clone https://github.com/yuvrajganguly/Automated_payment_system.git payout
cd payout && git checkout review/hardening
bash deploy/setup-server.sh          # firewall, docker, auto-updates
# 2 GB plan: add swap so builds never OOM
fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile \
  && swapon /swapfile && echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

## 3. The domain

Preferred: **payout.qwikserve.in** — qwikserve.in is registered (2020),
almost certainly by the company. Whoever manages its DNS adds one record:

```
Type A    Host: payout    Value: SERVER_IP    TTL: automatic
```

If the company's qwikserve.in isn't reachable/usable, buy one that contains
Qwikserve — qwikserve.org (~₹758/yr), qwikserve.app (~₹663/yr) or
qwikserve.co were open on Namecheap as of 2026-09-03 — and point the same
A record (host `payout`, or the bare domain) at `SERVER_IP`.

Until the DNS record exists you can still bring the system up on
`payout.<ip-with-dashes>.sslip.io` and switch `SITE_ADDRESS` later — Caddy
re-issues the certificate automatically on the next `up -d`.

## 4. Configure

```bash
cd ~/payout/deploy
cp .env.prod.example .env
openssl rand -hex 24                 # -> POSTGRES_PASSWORD
openssl rand -hex 32                 # -> PAYOUT_JWT_SECRET
nano .env                            # paste both; SITE_ADDRESS=payout.qwikserve.in
```

## 5. First boot

```bash
docker compose -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.prod.yml ps        # all healthy?
```

Open `https://payout.qwikserve.in` (or the sslip.io name) — the certificate
appears automatically once DNS resolves to the server. The database is empty;
don't create users if you're migrating — step 6 brings your real users along.

## 6. Migrate the data up from your local Docker

On your machine (PowerShell):

```powershell
docker exec payout-db pg_dump -U payout -Fc payout -f /tmp/payout.dump
docker cp payout-db:/tmp/payout.dump .\payout.dump
scp -i <path-to-key> .\payout.dump ubuntu@SERVER_IP:/tmp/
```

On the server (as root):

```bash
mv /tmp/payout.dump ~/payout/deploy/ && cd ~/payout/deploy
sh restore.sh payout.dump            # type RESTORE when asked
docker compose -f docker-compose.prod.yml restart app
```

Verify: log in with your REAL admin account and compare dashboard totals with
the local instance. Same numbers = migration done. From then on the cloud is
the single source of truth — local Docker becomes an offline backup only.

## 7. Lock it down (do not skip)

```bash
docker compose -f docker-compose.prod.yml exec db \
  psql -U payout -d payout -c \
  "UPDATE users SET is_active=0 WHERE email='admin@demo.com';"
```

Then in the app: change your own admin password to something strong and
unique. Every team-app user gets their OWN account with the least role that
works — never a shared login (the audit log is worthless otherwise). When
someone leaves, deactivate their account the same day.

## 8. Updating the deployment later

```bash
cd ~/payout && git pull
cd deploy && docker compose -f docker-compose.prod.yml up -d --build
```

## 9. Backups

- Nightly `pg_dump` in `~/payout/deploy/backups/`, 14 days kept.
- **Off-server copy** weekly (a dump file IS the whole business — bank
  accounts included — treat it like cash: never WhatsApp/email it, never in
  git or a shared OneDrive):
  `scp -i <key> ubuntu@SERVER_IP:payout/deploy/backups/<newest>.dump D:\payout-backups\`
- Lightsail also offers instance **snapshots** ($0.05/GB-mo) — enable
  automatic daily snapshots as a second layer.
- Restore drill: `sh restore.sh backups/<file>.dump` — practice once on day
  one so it's boring on the bad day.

## Notes for the coming team app

- The app calls the API over HTTPS at the SITE_ADDRESS URL — never the DB.
- Different origin → set `PAYOUT_CORS_ORIGINS` in `deploy/.env`, `up -d`.
- Each user: own account, least role; rate limiting is already server-side.
