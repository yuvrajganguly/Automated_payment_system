"""Aggregate rider figures that are safe to publish on the company website.

Only two counts leave this module: the number of distinct riders (people, not
rider IDs) ever onboarded, and how many of them hold at least one active rider
ID. No names, IDs, companies or any per-rider field are read into the result.

A person with two rider IDs (say Myntra and Blitz) counts once, matching how
person_registry merges identities. "Active" follows rider_master.is_active,
the same flag the console uses to retire a rider ID.
"""

from __future__ import annotations

from datetime import datetime, timezone


def rider_counts(conn) -> dict:
    row = conn.execute(
        "SELECT COUNT(DISTINCT person_id) AS total, "
        "COUNT(DISTINCT CASE WHEN is_active = 1 THEN person_id END) AS active "
        "FROM rider_master"
    ).fetchone()
    return {
        "riders_total": int(row["total"] or 0),
        "riders_active": int(row["active"] or 0),
        "as_of": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
