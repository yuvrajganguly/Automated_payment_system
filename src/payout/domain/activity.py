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
from contextvars import ContextVar
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
    "ev.closeout": "Closed out EV deposit",
    "ev.amend_return": "Amended EV return date",
    "ev.maintenance_open": "Sent EV to maintenance",
    "ev.maintenance_close": "Brought EV back from maintenance",
    "document.upload": "Uploaded document",
    "document.delete": "Deleted document",
    "request.create": "Requested money change",
    "request.approve": "Approved money request",
    "request.reject": "Rejected money request",
    "ev_request.create": "Asked for EVs",
    "ev_request.fulfil": "Fulfilled an EV request",
    "ev_request.reject": "Rejected an EV request",
    "ev_request.cancel": "Withdrew an EV request",
    "hub.update": "Updated a store",
    "referral.create": "Recorded a referral",
    "referral.void": "Cancelled a referral",
}


# Where the caller was when they acted. The recruiter app sends
# ``X-Client-Location: <lat>,<lng>,<accuracy_m>`` on every write; the API
# middleware parses it into this context variable so every activity row
# written during that request carries the stamp (see api/middleware.py).
# Nothing else about a request is captured — no background tracking.
client_location: ContextVar[tuple[float, float, float | None] | None] = ContextVar(
    "client_location", default=None
)


def parse_client_location(header: str | None) -> tuple[float, float, float | None] | None:
    """``"22.5726,88.3639,12"`` -> (22.5726, 88.3639, 12.0); junk -> None."""
    if not header:
        return None
    parts = [p.strip() for p in header.split(",")]
    if len(parts) < 2:
        return None
    try:
        lat, lng = float(parts[0]), float(parts[1])
        acc = float(parts[2]) if len(parts) > 2 and parts[2] else None
    except ValueError:
        return None
    if not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return lat, lng, acc


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
    loc = client_location.get()
    lat, lng, acc = loc if loc else (None, None, None)
    conn.execute(
        "INSERT INTO activity_log (email, role, action, entity_type, entity_id, entity_label, "
        "person_id, details, lat, lng, accuracy_m) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (
            user.get("email") or "",
            user.get("role"),
            action,
            entity_type,
            str(entity_id),
            label,
            person_id,
            blob,
            lat,
            lng,
            acc,
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
