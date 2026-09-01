"""Every table that references a person or an EV — in one place.

Person merges (``persons.link_riders``, ``creator.force_merge``) and the
creator's hard deletes each carried their own hand-written list of dependent
tables, and the lists disagreed: ``delete_person`` forgot
``ev_daily_ledger.assigned_person_id`` and deleted ``transactions`` before
``payment_lines`` (which references it), ``link_riders`` dropped the person
without re-pointing ``payment_lines`` — every one a foreign-key 500 or an
orphaned row. Keep this list in step with ``schema.py`` and use it everywhere.
"""

from __future__ import annotations

# (table, column) pairs that reference person_registry(person_id), ordered so
# that a DELETE in this order never violates a foreign key: children first.
PERSON_REFS: tuple[tuple[str, str], ...] = (
    ("payment_lines", "person_id"),        # -> transactions(id) too: must go first
    ("ev_daily_ledger", "assigned_person_id"),
    ("cod_holds", "person_id"),
    ("transactions", "person_id"),
    ("ev_assignments", "person_id"),
    ("rider_master", "person_id"),
    ("balances", "person_id"),
    ("ev_arrears", "person_id"),
    ("status_tracking", "person_id"),
)

# Tables whose person reference is "one row per person" (merging must SUM /
# drop them rather than re-point, or the primary key collides).
PERSON_SINGLETON_TABLES: frozenset[str] = frozenset({"balances", "ev_arrears", "status_tracking"})

# (table, column) pairs that reference ev_units(ev_id), children first.
EV_REFS: tuple[tuple[str, str], ...] = (
    ("ev_daily_ledger", "ev_id"),
    ("ev_assignments", "ev_id"),
    ("ev_maintenance", "ev_id"),
)


def repoint_person(conn, from_person_id: int, to_person_id: int) -> None:
    """Move every multi-row reference from one person to another. Singleton
    tables (balances, arrears, status) are left for the caller to merge."""
    for table, col in PERSON_REFS:
        if table in PERSON_SINGLETON_TABLES:
            continue
        conn.execute(
            f"UPDATE {table} SET {col}=? WHERE {col}=?", (to_person_id, from_person_id)
        )


def purge_person(conn, person_id: int) -> None:
    """Hard-delete a person and everything that points at them."""
    for table, col in PERSON_REFS:
        conn.execute(f"DELETE FROM {table} WHERE {col}=?", (person_id,))
    conn.execute("DELETE FROM person_registry WHERE person_id=?", (person_id,))


def drop_person_singletons(conn, person_id: int) -> None:
    """Remove the one-row-per-person tables + the registry row after a merge
    has re-pointed and summed everything else."""
    for table in PERSON_SINGLETON_TABLES:
        conn.execute(f"DELETE FROM {table} WHERE person_id=?", (person_id,))
    conn.execute("DELETE FROM person_registry WHERE person_id=?", (person_id,))


def purge_ev(conn, ev_id: str) -> None:
    """Hard-delete an EV and everything that points at it."""
    for table, col in EV_REFS:
        conn.execute(f"DELETE FROM {table} WHERE {col}=?", (ev_id,))
    conn.execute("DELETE FROM ev_units WHERE ev_id=?", (ev_id,))
