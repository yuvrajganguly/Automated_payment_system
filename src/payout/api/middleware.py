"""Audit-log middleware.

Captures method, path, status, duration, and a short request-body excerpt
for every state-changing request, attaching the caller's email + role when
the JWT is present. Read-only requests (GET / HEAD / OPTIONS) and static
asset hits are skipped to keep the table size sane.

Sensitive fields (password, otp, new_password) are scrubbed from the body
excerpt before persisting.
"""

from __future__ import annotations

import json
import re
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from payout.api.auth import decode_token
from payout.db import get_connection

_SENSITIVE_KEYS = re.compile(
    r'("(?:password|otp|new_password|current_password|access_token)"\s*:\s*)"[^"]*"',
    re.IGNORECASE,
)
_MAX_BODY = 500


def _scrub(s: str) -> str:
    return _SENSITIVE_KEYS.sub(r'\1"***"', s)


class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        path = request.url.path
        # Skip read-only methods + static assets entirely.
        if method in ("GET", "HEAD", "OPTIONS") or path.startswith("/static"):
            return await call_next(request)

        # Pull body BEFORE handing off so we can capture an excerpt. Starlette
        # caches it so downstream handlers still read normally.
        body_bytes = await request.body()
        body_excerpt = None
        if body_bytes:
            try:
                txt = body_bytes.decode(errors="replace")
                body_excerpt = _scrub(txt)[:_MAX_BODY]
            except Exception:
                body_excerpt = f"<{len(body_bytes)} bytes binary>"

        # Identify caller from the JWT (if any).
        email = role = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            try:
                payload = decode_token(auth.split(" ", 1)[1])
                email = payload.get("sub")
                role = payload.get("role")
            except Exception:
                pass

        ip = request.client.host if request.client else None

        t0 = time.perf_counter()
        response: Response = await call_next(request)
        duration_ms = int((time.perf_counter() - t0) * 1000)

        try:
            with get_connection() as conn:
                conn.execute(
                    "INSERT INTO audit_log "
                    "(email, role, method, path, status_code, duration_ms, "
                    " body_excerpt, ip) VALUES (?,?,?,?,?,?,?,?)",
                    (email, role, method, path, response.status_code,
                     duration_ms, body_excerpt, ip),
                )
                conn.commit()
        except Exception:
            # Never break the response over an audit-write failure.
            pass

        return response
