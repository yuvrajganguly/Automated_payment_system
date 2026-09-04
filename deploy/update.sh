#!/usr/bin/env bash
# Deploy the latest CI-built image on the server. Run as root:
#   /root/payout/deploy/update.sh
# (CI must have finished for the commit you want — Actions tab green.)
set -euo pipefail
cd "$(dirname "$0")"
git pull --ff-only
docker compose -f docker-compose.prod.yml pull app
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
echo "Deployed $(git rev-parse --short HEAD)"
