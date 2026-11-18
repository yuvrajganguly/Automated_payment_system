"""Explicit, transactional consolidation of the legacy Blitz roster.

Not a startup migration: production requires an inspected dry run and backup.
Only company metadata changes; no settlement or balance adjustment is run.
"""

from payout.db.references import COMPANY_REFS
from payout.domain.activity import record_activity
from payout.domain.placeholders import is_placeholder, retire_placeholders


def consolidate_blitz(conn) -> dict[str, int]:
    """Caller must commit or roll back. Conflicting records abort the operation.

    Matching IDs may collapse only when they belong to the same person. Keep
    Kaptan's configured parser and populated roster fields; fill missing fields
    from Nykaa. Never merge people or their balances implicitly.
    """
    sources = [
        name
        for name in ("Kaptan", "Nykaa")
        if conn.execute("SELECT 1 FROM companies WHERE company_name=?", (name,)).fetchone()
    ]
    if not sources:
        return {"companies": 0, "duplicate_ids": 0}
    conn.execute("SAVEPOINT consolidate_blitz")
    duplicates = 0
    try:
        target = conn.execute("SELECT * FROM companies WHERE company_name='Blitz'").fetchone()
        if target is None:
            source = dict(
                conn.execute(
                    "SELECT * FROM companies WHERE company_name=?", (sources[0],)
                ).fetchone()
            )
            source["company_name"] = "Blitz"
            source["rider_ids_shared_with"] = None
            columns = list(source)
            conn.execute(
                f"INSERT INTO companies ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                tuple(source.values()),
            )
        for old in sources:
            # A placeholder is local to its original company. Retire it into
            # this person's real ID before comparing identities across companies.
            for placeholder in conn.execute(
                "SELECT * FROM rider_master WHERE company=? AND rider_id LIKE 'QSPEND%'", (old,)
            ).fetchall():
                real = conn.execute(
                    "SELECT rider_id FROM rider_master WHERE company='Blitz' AND person_id=? "
                    "AND rider_id NOT LIKE 'QSPEND%' ORDER BY rider_id",
                    (placeholder["person_id"],),
                ).fetchone()
                if real:
                    values = dict(placeholder)
                    values["rider_id"] = real["rider_id"]
                    conn.execute(
                        f"INSERT OR IGNORE INTO rider_master ({', '.join(values)}) "
                        f"VALUES ({', '.join('?' for _ in values)})",
                        tuple(values.values()),
                    )
                    retire_placeholders(conn, placeholder["person_id"], old, real["rider_id"])
            for row in conn.execute(
                "SELECT * FROM rider_master WHERE company=?", (old,)
            ).fetchall():
                existing = conn.execute(
                    "SELECT * FROM rider_master WHERE company='Blitz' AND rider_id=?",
                    (row["rider_id"],),
                ).fetchone()
                if existing is None:
                    continue
                if existing["person_id"] != row["person_id"]:
                    raise ValueError(
                        "Matching rider IDs belong to different people; resolve first."
                    )
                for field in ("salary", "payment_model", "account_no", "ifsc"):
                    if existing[field] and row[field] and existing[field] != row[field]:
                        raise ValueError(f"Conflicting rider {field}; resolve before merging.")
                merged = {
                    key: existing[key] if existing[key] not in (None, "") else row[key]
                    for key in dict(row)
                    if key not in ("company", "rider_id", "person_id")
                }
                merged["is_active"] = max(existing["is_active"], row["is_active"])
                conn.execute(
                    "UPDATE rider_master SET "
                    + ", ".join(f"{key}=?" for key in merged)
                    + " WHERE company='Blitz' AND rider_id=?",
                    (*merged.values(), row["rider_id"]),
                )
                conn.execute(
                    "DELETE FROM rider_master WHERE company=? AND rider_id=?",
                    (old, row["rider_id"]),
                )
                duplicates += 1
            # Two legitimate companies may have paid in the same week. Keep
            # their combined summary, and archive both source summaries in the
            # activity log. Never discard an original saved workbook.
            for cycle in conn.execute(
                "SELECT * FROM company_cycles WHERE company=?", (old,)
            ).fetchall():
                other = conn.execute(
                    "SELECT * FROM company_cycles WHERE company='Blitz' "
                    "AND cycle_start=? AND cycle_end=?",
                    (cycle["cycle_start"], cycle["cycle_end"]),
                ).fetchone()
                if not other:
                    continue
                if conn.execute(
                    "SELECT 1 FROM payout_workbooks WHERE cycle_id IN (?,?)",
                    (cycle["id"], other["id"]),
                ).fetchone():
                    raise ValueError("Overlapping cycles have saved workbooks; archive them first.")
                record_activity(
                    conn,
                    {"email": "maintenance", "role": "creator"},
                    "company.consolidate",
                    entity_type="company",
                    entity_id="Blitz",
                    details={"source_cycles": [dict(cycle), dict(other)]},
                )
                totals = (
                    "rider_count",
                    "riders_paid",
                    "riders_in_dues",
                    "total_release",
                    "total_rent_charged",
                    "total_rent_collected",
                    "total_rent_missed",
                )
                conn.execute(
                    "UPDATE company_cycles SET "
                    + ", ".join(f"{k}={k}+?" for k in totals)
                    + " WHERE id=?",
                    (*[cycle[k] for k in totals], other["id"]),
                )
                conn.execute("DELETE FROM company_cycles WHERE id=?", (cycle["id"],))
            # Remaining collisions are errors, never silently discarded.
            refs = (
                *COMPANY_REFS,
                ("company_pincode_rates", "company"),
                ("payout_order_days", "company"),
                ("adhoc_runs", "company"),
            )
            for table, column in refs:
                conn.execute(f"UPDATE {table} SET {column}=? WHERE {column}=?", ("Blitz", old))
            conn.execute(
                "UPDATE activity_log SET entity_id=SUBSTR(entity_id,1,LENGTH(entity_id)-?) || ? "
                "WHERE SUBSTR(entity_id,LENGTH(entity_id)-?+1)=?",
                (len(old), "Blitz", len(old) + 1, f"@{old}"),
            )
            conn.execute(
                "UPDATE activity_log SET entity_id='Blitz' "
                "WHERE entity_type='company' AND entity_id=?",
                (old,),
            )
            conn.execute("DELETE FROM companies WHERE company_name=?", (old,))
        conn.execute(
            "UPDATE companies SET rider_ids_shared_with=NULL "
            "WHERE company_name='Blitz' AND rider_ids_shared_with='Blitz'"
        )
        for rider in conn.execute(
            "SELECT person_id,rider_id FROM rider_master WHERE company='Blitz'"
        ).fetchall():
            if not is_placeholder(rider["rider_id"]):
                retire_placeholders(conn, rider["person_id"], "Blitz", rider["rider_id"])
        conn.execute("RELEASE SAVEPOINT consolidate_blitz")
    except Exception:
        conn.execute("ROLLBACK TO SAVEPOINT consolidate_blitz")
        conn.execute("RELEASE SAVEPOINT consolidate_blitz")
        raise
    return {"companies": len(sources), "duplicate_ids": duplicates}
