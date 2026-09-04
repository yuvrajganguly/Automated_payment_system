"""Placeholder rider ids.

A rider onboarded before their company issued an id gets a system placeholder
(``QSPEND<NNNN>``, scoped per company). The moment a real id is tagged to that
person at that company the placeholder has done its job: its history moves
onto the real id and the placeholder row is deleted, so the roster never shows
two ids for one rider where one is a stand-in.
"""

from __future__ import annotations

PLACEHOLDER_PREFIX = "QSPEND"


def is_placeholder(rider_id: str | None) -> bool:
    return bool(rider_id) and str(rider_id).upper().startswith(PLACEHOLDER_PREFIX)


def retire_placeholders(conn, person_id: int, company: str, real_rider_id: str) -> list[str]:
    """Delete this person's placeholder ids at ``company`` now that
    ``real_rider_id`` exists there, moving every reference (transactions, COD
    holds, deduction anchor) onto the real id first. Returns the ids removed.
    A no-op when ``real_rider_id`` is itself a placeholder."""
    real = (real_rider_id or "").strip()
    if not real or is_placeholder(real):
        return []
    rows = conn.execute(
        "SELECT rider_id FROM rider_master "
        "WHERE person_id=? AND company=? AND rider_id LIKE ? AND rider_id<>?",
        (person_id, company, f"{PLACEHOLDER_PREFIX}%", real),
    ).fetchall()
    removed: list[str] = []
    for r in rows:
        old = r["rider_id"]
        conn.execute(
            "UPDATE transactions SET rider_id=? WHERE rider_id=? AND company=? AND person_id=?",
            (real, old, company, person_id),
        )
        conn.execute(
            "UPDATE cod_holds SET rider_id=? WHERE rider_id=? AND company=?",
            (real, old, company),
        )
        conn.execute(
            "UPDATE person_registry SET deduction_rider_id=? "
            "WHERE person_id=? AND deduction_company=? AND deduction_rider_id=?",
            (real, person_id, company, old),
        )
        conn.execute(
            "DELETE FROM rider_master WHERE rider_id=? AND company=? AND person_id=?",
            (old, company, person_id),
        )
        removed.append(old)
    return removed


def retire_placeholders_everywhere(conn, person_id: int) -> list[str]:
    """After a merge: at every company where the person now holds a real id,
    drop the placeholders."""
    removed: list[str] = []
    rows = conn.execute(
        "SELECT company, MIN(rider_id) AS real_id FROM rider_master "
        "WHERE person_id=? AND rider_id NOT LIKE ? GROUP BY company",
        (person_id, f"{PLACEHOLDER_PREFIX}%"),
    ).fetchall()
    for r in rows:
        removed += retire_placeholders(conn, person_id, r["company"], r["real_id"])
    return removed


__all__ = [
    "PLACEHOLDER_PREFIX",
    "is_placeholder",
    "retire_placeholders",
    "retire_placeholders_everywhere",
]
