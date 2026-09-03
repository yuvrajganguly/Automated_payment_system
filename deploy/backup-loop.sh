#!/bin/sh
# Nightly compressed Postgres dump with rotation. Runs as the `backup`
# sidecar's entrypoint. First dump happens ~60s after boot (so a fresh deploy
# is backed up immediately), then daily.
set -eu

KEEP_DAYS="${BACKUP_KEEP_DAYS:-14}"
sleep 60
while :; do
  ts=$(date +%Y%m%d-%H%M%S)
  if pg_dump -h db -U payout -Fc payout > "/backups/payout-${ts}.dump.tmp"; then
    mv "/backups/payout-${ts}.dump.tmp" "/backups/payout-${ts}.dump"
    echo "backup ok: payout-${ts}.dump ($(du -h "/backups/payout-${ts}.dump" | cut -f1))"
  else
    rm -f "/backups/payout-${ts}.dump.tmp"
    echo "backup FAILED at ${ts}" >&2
  fi
  # rotate
  find /backups -name 'payout-*.dump' -mtime +"${KEEP_DAYS}" -delete
  sleep 86400
done
