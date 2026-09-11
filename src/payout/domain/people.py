"""One row per person, out of rider_master rows.

A person holds one rider id per company they work for — Kaptan and Nykaa, say
— and every *count* in this system counts people: a recruiter recruits humans,
not ids. The lists beside those counts were built straight off rider_master,
so a two-id rider was two entries under a tile that had counted him once. A
list that disagrees with the number above it is worse than no list.

This is the collapse both the app's "latest onboardings" and the recruiter
drilldowns run through, so they cannot drift apart.
"""

from __future__ import annotations


def by_person(rows) -> list[dict]:
    """Collapse rider_master rows into one row per person, newest recruit
    first.

    Merging rules, each chosen so the row cannot contradict a count:

    * ``created_at`` is the EARLIEST of the person's ids — the day they were
      recruited. The period counts use the same MIN.
    * ``working`` is already a property of the person, so any row will do; it
      is ORed anyway so a stale disagreement cannot read as idle.
    * ``on_roster`` is true if ANY id is switched on, matching how
      ``on_roster`` is counted.
    * ``hub`` and ``ev_id`` take the first non-empty. A person works one store
      in practice, and holds at most one EV by construction.
    """
    people: dict[int, dict] = {}
    for r in rows:
        pid = int(r["person_id"])
        p = people.get(pid)
        if p is None:
            people[pid] = {
                "rider_id": r["rider_id"],
                "company_name": r["company"],
                "companies": [r["company"]],
                "rider_ids": [r["rider_id"]],
                "name": r["name"],
                "person_id": pid,
                "hub": r["hub"],
                "created_at": r["created_at"],
                "on_roster": bool(r["is_active"]),
                "working": bool(r["working"]),
                "last_worked_on": r["last_worked_on"],
                "ev_id": r["ev_id"],
            }
            continue
        if r["company"] not in p["companies"]:
            p["companies"].append(r["company"])
        if r["rider_id"] not in p["rider_ids"]:
            p["rider_ids"].append(r["rider_id"])
        p["on_roster"] = p["on_roster"] or bool(r["is_active"])
        p["working"] = p["working"] or bool(r["working"])
        p["hub"] = p["hub"] or r["hub"]
        p["ev_id"] = p["ev_id"] or r["ev_id"]
        p["name"] = p["name"] or r["name"]
        if r["created_at"] and (not p["created_at"] or r["created_at"] < p["created_at"]):
            # The earlier id is the recruitment; its id and company lead.
            p["created_at"] = r["created_at"]
            p["rider_id"] = r["rider_id"]
            p["company_name"] = r["company"]
        if r["last_worked_on"] and (
            not p["last_worked_on"] or r["last_worked_on"] > p["last_worked_on"]
        ):
            p["last_worked_on"] = r["last_worked_on"]
    out = list(people.values())
    for p in out:
        p["companies"].sort()
        p["rider_ids"].sort()
    out.sort(key=lambda p: (p["created_at"] or "", p["rider_id"]), reverse=True)
    return out


__all__ = ["by_person"]
