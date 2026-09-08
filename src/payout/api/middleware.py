"""Audit-log middleware.

Captures method, path, status, duration, and a short request-body excerpt
for every state-changing request, attaching the caller's email + role when
the JWT is present. Read-only requests (GET / HEAD / OPTIONS) and static
asset hits are skipped to keep the table size sane.

Sensitive fields (password, otp, new_password) are scrubbed from the body
excerpt before persisting.
"""

from __future__ import annotations

import re
import time

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from payout.api.auth import decode_token
from payout.api.config import AUTH_COOKIE_NAME
from payout.db import get_connection

# Two families, both redacted from the stored request body.
#
# Credentials, which were never meant to be here at all. And identity and bank
# numbers, which arrive on rider onboarding and on a recruiter saving their own
# profile: the routes that write them go to real trouble to keep the values out
# of the activity feed, and it would be undone one layer up if the audit log
# kept a verbatim copy of the request. That matters more since 2026-09, when
# the audit log opened from creator-only to every admin.
_SENSITIVE_FIELDS = (
    "password",
    "otp",
    "new_password",
    "current_password",
    "access_token",
    "aadhaar_no",
    "aadhaar",
    "pan_no",
    "pan",
    "account_no",
    "bene_account_no",
    "ifsc",
)
_SENSITIVE_KEYS = re.compile(
    r'("(?:' + "|".join(_SENSITIVE_FIELDS) + r')"\s*:\s*)"[^"]*"',
    re.IGNORECASE,
)
# Same fields when the body is application/x-www-form-urlencoded (OAuth2 login).
_SENSITIVE_FORM = re.compile(r"\b(" + "|".join(_SENSITIVE_FIELDS) + r")=[^&]*", re.IGNORECASE)
_MAX_BODY = 500
# Bodies on these routes are credentials by definition — never store them, even
# scrubbed. (The form-encoded login body used to be logged verbatim.)
_NO_BODY_PREFIXES = ("/api/auth/",)


def _scrub(s: str) -> str:
    s = _SENSITIVE_KEYS.sub(r'\1"***"', s)
    return _SENSITIVE_FORM.sub(r"\1=***", s)


class ClientLocationMiddleware(BaseHTTPMiddleware):
    """Parse the recruiter app's ``X-Client-Location`` header into the
    activity log's context variable for the life of this request."""

    async def dispatch(self, request: Request, call_next):
        from payout.domain.activity import client_location, parse_client_location

        token = client_location.set(parse_client_location(request.headers.get("x-client-location")))
        try:
            return await call_next(request)
        finally:
            client_location.reset(token)


class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        method = request.method.upper()
        path = request.url.path
        # Skip read-only methods + static assets entirely.
        if method in ("GET", "HEAD", "OPTIONS") or path.startswith("/static"):
            return await call_next(request)

        # Pull body BEFORE handing off so we can capture an excerpt. Starlette
        # caches it so downstream handlers still read normally.
        body_excerpt = None
        if path.startswith(_NO_BODY_PREFIXES):
            body_bytes = b""
        else:
            body_bytes = await request.body()
        if body_bytes:
            try:
                txt = body_bytes.decode(errors="replace")
                body_excerpt = _scrub(txt)[:_MAX_BODY]
            except Exception:
                body_excerpt = f"<{len(body_bytes)} bytes binary>"

        # Identify caller from the JWT (if any) — Bearer header or auth cookie.
        email = role = None
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth.split(" ", 1)[1]
        else:
            token = request.cookies.get(AUTH_COOKIE_NAME)
        if token:
            try:
                payload = decode_token(token)
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
                    (
                        email,
                        role,
                        method,
                        path,
                        response.status_code,
                        duration_ms,
                        body_excerpt,
                        ip,
                    ),
                )
                conn.commit()
        except Exception:
            # Never break the response over an audit-write failure.
            pass

        return response


class RupeeizeMiddleware(BaseHTTPMiddleware):
    """Convert internal integer **paise** to rupee floats on the way out.

    Domain + DB store money as paise; this is the single egress point that
    turns every JSON money field (see payout.money.MONEY_KEYS) back into
    rupees so the API/clients are unchanged. Binary downloads (xlsx) skip this
    and convert in their own builders.
    """

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        ctype = response.headers.get("content-type", "")
        if not ctype.startswith("application/json"):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        try:
            import json as _json

            from payout.money import rupeeize

            data = rupeeize(_json.loads(body))
            payload = _json.dumps(data).encode("utf-8")
        except Exception:
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=ctype,
            )
        headers = dict(response.headers)
        headers.pop("content-length", None)
        return Response(
            content=payload,
            status_code=response.status_code,
            headers=headers,
            media_type="application/json",
        )
