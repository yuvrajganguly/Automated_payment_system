"""Unauthenticated, read-only figures for the public company website.

GET /api/public/rider-stats returns aggregate counts only (see
payout.domain.public_stats). The answer is cached in-process for five minutes,
so however busy the website gets the database sees at most one small COUNT
query per five minutes. There is deliberately no per-IP rate limit: uvicorn runs
without --proxy-headers behind Caddy, so every visitor would share one bucket
and a limit would throttle the website as a whole.

The response carries ``Access-Control-Allow-Origin: *`` so the static website
(a different origin) can read it. No cookies or credentials are involved.
"""

from __future__ import annotations

import threading
import time

from fastapi import APIRouter, Response

from payout.db import get_connection
from payout.domain.public_stats import rider_counts

router = APIRouter()

CACHE_SECONDS = 300
_cache: dict = {"at": 0.0, "body": None}
_lock = threading.Lock()


def reset_cache() -> None:
    """Forget the cached figures (tests)."""
    with _lock:
        _cache["at"], _cache["body"] = 0.0, None


@router.get("/rider-stats")
def rider_stats(response: Response) -> dict:
    now = time.monotonic()
    with _lock:
        if _cache["body"] is None or now - _cache["at"] > CACHE_SECONDS:
            with get_connection() as conn:
                _cache["body"] = rider_counts(conn)
            _cache["at"] = now
        body = dict(_cache["body"])
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Cache-Control"] = f"public, max-age={CACHE_SECONDS}"
    return body
