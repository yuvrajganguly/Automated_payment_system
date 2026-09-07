"""Activity feed — what each operator did (see payout.domain.activity).

GET /api/activity?email=&action=&entity_type=&person_id=&since=&limit=
    admin/creator: everything, filterable by who; recruiter: own rows only.
GET /api/activity/people   who has activity, with counts (for the filter)

Rows carry ``lat`` / ``lng`` / ``accuracy_m`` when the caller sent
``X-Client-Location`` — the recruiter app stamps its writes, so an admin can
see where an onboarding actually happened. It is null for everything done
from the web console. Where the recruiter *was* over a day is a different
question with a different answer: ``GET /app/locations``.
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
        "details, lat, lng, accuracy_m FROM activity_log"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row(r) for r in rows]


@router.get("/changes")
def activity_changes(
    since: int | None = Query(default=None, ge=0, description="the cursor you last saw"),
    _: dict = Depends(get_current_user),
) -> dict:
    """A cheap "has anything happened?" for the console to poll.

    The web console used to paint itself once and then quietly go out of date:
    a rider onboarded from the phone was on the server immediately, but a page
    opened before that kept showing the roster without them — which is how two
    people onboard the same rider twice. Rather than push events at browsers
    (this runs as a single uvicorn process today, but should not depend on
    that), the console asks for a cursor every few seconds. It is one indexed
    read of the activity log, and `changed` tells the page whether the thing it
    is showing is the thing that moved.
    """
    with get_connection() as conn:
        cursor = conn.execute("SELECT COALESCE(MAX(id), 0) FROM activity_log").fetchone()[0]
        changed: list[str] = []
        if since is not None:
            rows = conn.execute(
                "SELECT DISTINCT entity_type FROM activity_log "
                "WHERE id > ? AND entity_type IS NOT NULL",
                (since,),
            ).fetchall()
            changed = sorted(str(r[0]) for r in rows)
    return {"cursor": int(cursor or 0), "changed": changed}


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
