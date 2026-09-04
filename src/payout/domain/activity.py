"""Activity log — what people did, in business terms.

``audit_log`` (the middleware) records raw HTTP: method, path, status, a body
excerpt. That is a forensic trail, not something an admin can read to answer
"what did this recruiter do today?". ``activity_log`` is the readable answer:
one row per operator action on a rider, person, EV, document or money
request, written by the route that performed it, in the same transaction.

Usage inside a route (the connection is already open)::

    record_activity(
        conn, user, "rider.update",
        entity_type="rider", entity_id=f"{rider_id}@{company}",
        label=name, person_id=pid,
        details={"changed": {"hub": ["NTS", "South City"]}},
    )

Actions are dotted ``<entity>.<verb>`` strings; keep them stable — the
Activity page groups and filters on them.
"""

from __future__ import annotations

import json
from typing import Any

ACTIONS: dict[str, str] = {
    "rider.create": "Added rider",
    "rider.update": "Edited rider",
    "rider.rename": "Tagged rider id",
    "rider.link": "Linked rider id to existing person",
    "rider.delete": "Deleted rider",
    "person.merge": "Merged two people",
    "person.split": "Split a person",
    "ev.create": "Added EV",
    "ev.assign": "Assigned EV",
    "ev.return": "Returned EV",
    "ev.spare": "Marked EV spare",
    "ev.amend_return": "Amended EV return date",
    "ev.maintenance_open": "Sent EV to maintenance",
    "ev.maintenance_close": "Brought EV back from maintenance",
    "document.upload": "Uploaded document",
    "document.delete": "Deleted document",
    "request.create": "Requested money change",
    "request.approve": "Approved money request",
    "request.reject": "Rejected money request",
}


def record_activity(
    conn: Any,
    user: dict,
    action: str,
    *,
    entity_type: str,
    entity_id: str | int,
    label: str | None = None,
    person_id: int | None = None,
    details: dict | None = None,
) -> None:
    """Append one activity row. Never raises for a bad ``details`` — the log
    must not be the reason an operator's action fails."""
    try:
        blob = json.dumps(details, default=str, ensure_ascii=False) if details else None
    except (TypeError, ValueError):
        blob = json.dumps({"repr": repr(details)})
    conn.execute(
        "INSERT INTO activity_log (email, role, action, entity_type, entity_id, entity_label, "
        "person_id, details) VALUES (?,?,?,?,?,?,?,?)",
        (
            user.get("email") or "",
            user.get("role"),
            action,
            entity_type,
            str(entity_id),
            label,
            person_id,
            blob,
        ),
    )


def diff_fields(before: dict, after: dict, keys) -> dict[str, list]:
    """``{field: [old, new]}`` for every key whose value changed."""
    out: dict[str, list] = {}
    for k in keys:
        b, a = before.get(k), after.get(k)
        if (b or None) != (a or None):
            out[k] = [b, a]
    return out


__all__ = ["ACTIONS", "record_activity", "diff_fields"]
