"""Activity feed — what each operator did (see payout.domain.activity).

GET /api/activity?email=&action=&entity_type=&person_id=&since=&limit=
    admin/creator: everything, filterable by who; recruiter: own rows only.
GET /api/activity/people   who has activity, with counts (for the filter)
GET /api/activity/actions  action codes → labels
"""

from __future__ import annotations

import contextlib
import json

from fastapi import APIRouter, Depends, Query

from payout.api.auth import get_current_user
from payout.db import get_connection
from payout.domain.activity import ACTIONS

router = APIRouter()


def _row(r) -> dict:
    d = dict(r)
    with contextlib.suppress(TypeError, ValueError):
        d["details"] = json.loads(d["details"]) if d.get("details") else None
    d["action_label"] = ACTIONS.get(d["action"], d["action"])
    return d


@router.get("")
def list_activity(
    email: str | None = Query(default=None),
    action: str | None = Query(default=None),
    entity_type: str | None = Query(default=None),
    person_id: int | None = Query(default=None),
    since: str | None = Query(default=None, description="ISO date/time lower bound"),
    limit: int = Query(default=200, ge=1, le=2000),
    user: dict = Depends(get_current_user),
) -> list[dict]:
    where, params = [], []
    if user["role"] in ("admin", "creator"):
        if email:
            where.append("email=?")
            params.append(email.strip().lower())
    else:
        # Recruiters and viewers see their own trail only.
        where.append("email=?")
        params.append(user["email"])
    if action:
        where.append("action=?")
        params.append(action)
    if entity_type:
        where.append("entity_type=?")
        params.append(entity_type)
    if person_id is not None:
        where.append("person_id=?")
        params.append(person_id)
    if since:
        where.append("at>=?")
        params.append(since)
    sql = (
        "SELECT id, at, email, role, action, entity_type, entity_id, entity_label, person_id, "
        "details FROM activity_log"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row(r) for r in rows]


@router.get("/people")
def activity_people(user: dict = Depends(get_current_user)) -> list[dict]:
    """Operators with activity: email, role of their latest row, count, last seen."""
    with get_connection() as conn:
        if user["role"] in ("admin", "creator"):
            rows = conn.execute(
                "SELECT email, MAX(role) AS role, COUNT(*) AS actions, MAX(at) AS last_at "
                "FROM activity_log GROUP BY email ORDER BY last_at DESC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT email, MAX(role) AS role, COUNT(*) AS actions, MAX(at) AS last_at "
                "FROM activity_log WHERE email=? GROUP BY email",
                (user["email"],),
            ).fetchall()
    return [dict(r) for r in rows]


@router.get("/actions")
def activity_actions(_: dict = Depends(get_current_user)) -> dict:
    return dict(ACTIONS)
