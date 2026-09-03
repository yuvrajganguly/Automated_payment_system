#!/bin/sh
# Restore a dump into the running production database. DESTRUCTIVE — the
# current contents of the payout DB are replaced by the dump.
#
#   ./restore.sh backups/payout-20260903-020000.dump
#
set -eu
DUMP="${1:?usage: ./restore.sh <path-to-.dump>}"
[ -f "$DUMP" ] || { echo "no such file: $DUMP" >&2; exit 1; }

echo "Restoring $DUMP into the payout database (replaces current data)."
printf "Type RESTORE to continue: "
read -r answer
[ "$answer" = "RESTORE" ] || { echo "aborted"; exit 1; }

docker compose -f docker-compose.prod.yml exec -T db \
  pg_restore -U payout -d payout --clean --if-exists --no-owner < "$DUMP"
echo "done — restart the app so nothing stale is cached:"
echo "  docker compose -f docker-compose.prod.yml restart app"
