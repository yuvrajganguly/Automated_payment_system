"""Every table that references a person, an EV or a company — in one place.

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
    ("payment_lines", "person_id"),  # -> transactions(id) too: must go first
    ("referrals", "new_person_id"),
    ("referrals", "referrer_person_id"),
    ("ev_closeouts", "person_id"),  # -> ev_assignments(assignment_id) too: before it
    ("rider_documents", "person_id"),  # index rows only; objects stay in the store
    ("money_requests", "person_id"),
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


# (table, column) pairs holding a company NAME as text. ``companies.company_name``
# is the primary key — there is no surrogate id — so the name is copied verbatim
# into every table below, several of them inside a composite primary key or a
# UNIQUE constraint. Renaming a company means updating all of them in one
# transaction; miss one and its rows point at a company that no longer exists.
COMPANY_REFS: tuple[tuple[str, str], ...] = (
    ("person_registry", "deduction_company"),
    ("rider_master", "company"),  # part of PK (rider_id, company)
    ("transactions", "company"),
    ("balances", "xc_origin_company"),
    ("cod_holds", "company"),
    ("hub_codes", "company"),  # part of PK (company, code)
    ("company_hubs", "company"),  # part of PK (company, hub)
    ("referrals", "company"),
    ("ev_requests", "company"),
    ("salary_inputs", "company"),
    ("company_cycles", "company"),  # part of UNIQUE(company, cycle_start, cycle_end)
    ("companies", "rider_ids_shared_with"),  # company -> company pointer
)


def rename_company(conn, old: str, new: str) -> bool:
    """Rename a company everywhere, including history.

    Returns False, changing nothing, when there is no such company or the new
    name is already taken — both make this a no-op, so the caller can run it
    twice. Raises ``ValueError``, changing nothing, when rows already sit under
    the new name in a table that keys on (company, …); see below.

    ``activity_log.entity_id`` carries a composite ``rider_id@company`` string
    baked in at write time; it is rewritten by suffix here so the feed keeps
    resolving. The name is always bound as a parameter: a double-quoted
    "Spencer's" is an identifier on PostgreSQL, not a string.
    """
    if old == new:
        return False
    have = {r[0] for r in conn.execute(
        "SELECT company_name FROM companies WHERE company_name IN (?, ?)", (old, new)
    ).fetchall()}
    if old not in have or new in have:
        return False

    # Four of the tables below carry the company inside a composite primary key
    # or a UNIQUE constraint, so a row already sitting under the new name would
    # make the UPDATE raise. Migrations run as one transaction, so that would
    # roll the whole batch back and the app would fail to start — a rename is
    # not worth an outage. This is reachable in practice: deleting a company
    # leaves company_hubs rows behind, and a later rename onto that name
    # collides with them. Report the clash instead, and change nothing.
    for table, key in (
        ("rider_master", "rider_id"),
        ("hub_codes", "code"),
        ("company_hubs", "hub"),
        ("company_cycles", "cycle_start"),
    ):
        clash = conn.execute(
            f"SELECT COUNT(*) FROM {table} a JOIN {table} b "  # noqa: S608 - literals above
            f"ON a.{key} = b.{key} WHERE a.company=? AND b.company=?",
            (old, new),
        ).fetchone()[0]
        if clash:
            raise ValueError(
                f"cannot rename {old!r} to {new!r}: {clash} row(s) in {table} already "
                f"exist under {new!r}. Merge or remove them first."
            )

    # The PK row first: every other table holds a copy, not a real foreign key,
    # so the order only matters for readability.
    conn.execute("UPDATE companies SET company_name=? WHERE company_name=?", (new, old))
    for table, col in COMPANY_REFS:
        conn.execute(f"UPDATE {table} SET {col}=? WHERE {col}=?", (new, old))
    # entity_id is "<rider_id>@<company>": keep everything up to the '@' and
    # re-attach the new name. LENGTH(old) counts the name only, so the '@'
    # survives the trim, and trimming from the right means a rider_id that
    # itself contains the company name is not corrupted.
    #
    # The match is an exact suffix comparison rather than LIKE '%@<old>'. A
    # company name is data: '_' and '%' are LIKE wildcards, so a company called
    # Big_Basket would have matched (and rewritten) BigXBasket's rows. Worse,
    # SQLite's LIKE is case-insensitive and PostgreSQL's is not, so the same
    # migration would have produced different data on the two backends.
    conn.execute(
        "UPDATE activity_log SET entity_id = SUBSTR(entity_id, 1, LENGTH(entity_id) - ?) || ? "
        "WHERE SUBSTR(entity_id, LENGTH(entity_id) - ? + 1) = ?",
        (len(old), new, len(old) + 1, f"@{old}"),
    )
    return True


def repoint_person(conn, from_person_id: int, to_person_id: int) -> None:
    """Move every multi-row reference from one person to another. Singleton
    tables (balances, arrears, status) are left for the caller to merge."""
    for table, col in PERSON_REFS:
        if table in PERSON_SINGLETON_TABLES:
            continue
        conn.execute(f"UPDATE {table} SET {col}=? WHERE {col}=?", (to_person_id, from_person_id))


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
