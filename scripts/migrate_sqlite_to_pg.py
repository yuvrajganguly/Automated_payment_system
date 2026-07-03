r"""Copy a SQLite payout database into a fresh PostgreSQL database.

One-way, idempotent-ish (loads into empty tables). Never mutates the SQLite
source — always run it against a BACKUP copy, not the live file.

    python scripts/migrate_sqlite_to_pg.py  C:\payout_data\payout_backup.db  \
        postgresql://payout:pass@localhost:5432/payout

Steps: create the schema on Postgres, copy every table's rows verbatim (FK
checks deferred during load), then fast-forward each identity sequence past the
copied ids so new inserts don't collide.
"""
from __future__ import annotations

import os
import sqlite3
import sys

if len(sys.argv) != 3:
    print(__doc__)
    sys.exit(1)

SQLITE_PATH, PG_URL = sys.argv[1], sys.argv[2]

# Route the payout package at Postgres so apply_schema emits Postgres DDL.
os.environ["PAYOUT_DB_URL"] = PG_URL

import psycopg  # noqa: E402
from payout.db import get_connection  # noqa: E402
from payout.db.schema import apply_schema  # noqa: E402

# 1) Build the schema on Postgres (translated DDL; no reference seeding — we copy
#    every table, including companies/ev_models, straight from SQLite).
with get_connection() as pg:
    apply_schema(pg)
    pg.commit()
print("[migrate] schema created on Postgres")

# 2) Copy every user table.
src = sqlite3.connect(SQLITE_PATH)
src.row_factory = sqlite3.Row
tables = [r[0] for r in src.execute(
    "SELECT name FROM sqlite_master WHERE type='table' "
    "AND name NOT LIKE 'sqlite_%'")]

raw = psycopg.connect(PG_URL, autocommit=False)
cur = raw.cursor()
cur.execute("SET session_replication_role = replica")  # defer FK checks

total = 0
for t in tables:
    cols = [c[1] for c in src.execute(f"PRAGMA table_info({t})")]
    if not cols:
        continue
    rows = src.execute(f'SELECT {",".join(cols)} FROM {t}').fetchall()
    if not rows:
        print(f"[migrate] {t:24} 0")
        continue
    # All numeric columns in the PG schema are BIGINT (money = integer paise);
    # coerce any stray float to int so assignment is exact.
    def clean(v):
        # Money columns are BIGINT (integer paise) -> coerce any stray float.
        if isinstance(v, float):
            return int(round(v))
        # Postgres text can't hold NUL bytes; SQLite text can. Strip them.
        if isinstance(v, str) and "\x00" in v:
            return v.replace("\x00", "")
        return v
    data = [tuple(clean(v) for v in r) for r in rows]
    ph = ",".join(["%s"] * len(cols))
    cur.executemany(
        f'INSERT INTO {t} ({",".join(cols)}) VALUES ({ph})', data)
    print(f"[migrate] {t:24} {len(rows)}")
    total += len(rows)

cur.execute("SET session_replication_role = DEFAULT")
raw.commit()
print(f"[migrate] copied {total} rows across {len(tables)} tables")

# 3) Fast-forward identity sequences past the copied ids.
cur.execute(
    "SELECT table_name, column_name FROM information_schema.columns "
    "WHERE is_identity='YES'")
for tbl, col in cur.fetchall():
    cur.execute(
        f"SELECT setval(pg_get_serial_sequence('{tbl}', '{col}'), "
        f"COALESCE((SELECT MAX({col}) FROM {tbl}), 1))")
raw.commit()
print("[migrate] identity sequences reset")

src.close()
raw.close()
print("[migrate] done.")
