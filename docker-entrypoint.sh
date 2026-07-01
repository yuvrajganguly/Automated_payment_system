#!/bin/sh
set -e
# Make the data volume writable by the non-root app user, then drop privileges.
# Cheap: only the SQLite DB lives under /data.
mkdir -p /data
chown -R app:app /data
exec gosu app "$@"
