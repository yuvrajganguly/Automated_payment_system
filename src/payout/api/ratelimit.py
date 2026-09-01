"""Small in-process rate limiter for the unauthenticated auth routes.

Fixed window per (bucket, client IP). Deliberately dependency-free: this app
runs as a single uvicorn process for one operator, so a shared store would be
over-engineering. If it ever runs multi-worker, swap ``_HITS`` for Redis and
keep the same dependency signature.

Usage::

    @router.post("/login", dependencies=[Depends(rate_limit("login", 20, 60))])
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

_HITS: dict[tuple[str, str], deque[float]] = defaultdict(deque)
_LOCK = threading.Lock()


def _client_ip(request: Request) -> str:
    # Behind a reverse proxy uvicorn must be started with --proxy-headers for
    # request.client to be the real address; otherwise every caller shares one
    # bucket, which fails safe (stricter), not open.
    return request.client.host if request.client else "unknown"


def rate_limit(bucket: str, limit: int, window_seconds: int):
    """Return a FastAPI dependency allowing ``limit`` calls per ``window_seconds``
    per client IP for this ``bucket``. Exceeding it raises 429."""

    def _dep(request: Request) -> None:
        key = (bucket, _client_ip(request))
        now = time.monotonic()
        with _LOCK:
            q = _HITS[key]
            while q and now - q[0] > window_seconds:
                q.popleft()
            if len(q) >= limit:
                retry = int(window_seconds - (now - q[0])) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Too many attempts. Try again in a minute.",
                    headers={"Retry-After": str(retry)},
                )
            q.append(now)

    return _dep


def reset() -> None:
    """Clear all counters (tests)."""
    with _LOCK:
        _HITS.clear()
