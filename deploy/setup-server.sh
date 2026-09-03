#!/bin/bash
# One-time server preparation for a fresh Ubuntu 24.04 Hetzner VPS.
# Run as root right after the server is created:
#   bash setup-server.sh
set -euo pipefail

echo "== updates + basics =="
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get upgrade -y -qq
apt-get install -y -qq ca-certificates curl git ufw unattended-upgrades

echo "== automatic security updates =="
dpkg-reconfigure -f noninteractive unattended-upgrades

echo "== firewall: SSH + HTTP/HTTPS only =="
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "== docker =="
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

echo "== done =="
echo "Next: clone the repo and follow deploy/DEPLOY.md"
