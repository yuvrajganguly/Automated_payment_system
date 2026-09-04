# Deploying the real system to AWS Lightsail (Mumbai)

The production stack is `deploy/docker-compose.prod.yml`: Caddy terminates
HTTPS (automatic Let's Encrypt), the app and Postgres run on an internal
network with nothing else exposed, and a sidecar takes nightly dumps into
`deploy/backups/`. Lightsail disks are encrypted at rest by default.

Sizing: the **Micro plan — $7/mo, 2 vCPU / 1 GB / 40 GB SSD** — carries this
workload including the coming 12–20-user recruiter app. The stack idles at
300–400 MB; what used to need 2 GB was building the Docker image on the
server, and that now happens in GitHub Actions (the `docker` job publishes to
GHCR on every push to `main` / `review/hardening`). The server only pulls.
Mumbai (`ap-south-1`) includes 2 TB transfer/month, ~100× what this uses.
Never run `--build` on the Micro; if you must build on the box, take the $12
Small instead.

---

## 0. Before anything: get the code onto GitHub

The server pulls the code *and* the image from GitHub, so the branch must be
pushed first and CI must have gone green once (Actions tab → the "Docker ·
image builds" job publishes `ghcr.io/yuvrajganguly/automated_payment_system`).
On your machine:

```powershell
git push -u origin review/hardening
```

**Image visibility.** GHCR packages start private. Either make the package
public (github.com → your profile → Packages → `automated_payment_system` →
Package settings → Change visibility) — the image holds only code that is
already in the repo, no secrets — or keep it private and give the server a
read-only token: GitHub → Settings → Developer settings → Personal access
tokens (classic) → scope `read:packages` only; you will `docker login` with
it in step 5.

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
3. Image: **OS only → Ubuntu 24.04 LTS**. Plan: **$7 Micro (1 GB)**.
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
# 1 GB plan: 1 GB of swap is headroom for Postgres + a busy payout run
fallocate -l 1G /swapfile && chmod 600 /swapfile && mkswap /swapfile \
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
# private package only: docker login ghcr.io -u yuvrajganguly   (paste the read:packages token)
docker compose -f docker-compose.prod.yml pull app
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps        # all healthy?
```

(`pull app` first, always. Without it Compose would try to *build* the image
because the file also carries a `build:` fallback — and a build on 1 GB dies.)

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

Push to the branch, wait for CI to publish the image, then on the server:
`/root/payout/deploy/update.sh` (does all of the following), or by hand:

```bash
cd ~/payout && git pull                      # compose files / runbook / scripts
cd deploy && docker compose -f docker-compose.prod.yml pull app \
          && docker compose -f docker-compose.prod.yml up -d
docker image prune -f                        # drop the previous image
```

To hold or roll back a version, set `PAYOUT_IMAGE_TAG=<short sha>` in
`deploy/.env` (every push is also tagged with its commit SHA) and `up -d`.

## 9. Backups

- Nightly `pg_dump` in `~/payout/deploy/backups/`, 14 days kept.
- Rider documents (recruiter-app uploads) live in the `payout_docs` volume and
  are tarred nightly into the same folder (`documents-<ts>.tgz`). If you move
  them to an R2/S3 bucket (`PAYOUT_DOCS_S3_*` in `.env`) the bucket is the copy
  of record and the tarball step is skipped.
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
- Recruiters get the `recruiter` role (creator creates them on the Users page).
  The endpoints the app uses are listed in `docs/RECRUITER_API.md`.
