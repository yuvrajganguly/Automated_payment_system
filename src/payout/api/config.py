"""API configuration (JWT secret, CORS, token expiry, auth cookie)."""

from __future__ import annotations

import os
from datetime import timedelta

JWT_SECRET: str = os.environ.get("PAYOUT_JWT_SECRET", "dev-secret-change-me-in-production")
JWT_ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRES: timedelta = timedelta(hours=12)
CORS_ORIGINS: list[str] = [
    o.strip() for o in os.environ.get(
        "PAYOUT_CORS_ORIGINS",
        "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173",
    ).split(",") if o.strip()
]

# ── Auth cookie ──────────────────────────────────────────────────────────────
# The JWT is delivered to browsers as an httpOnly cookie (not reachable from JS,
# so it can't be exfiltrated by XSS). API/script clients may still send it as a
# Bearer header. Frontend and API are same-origin (Vite proxy in dev, FastAPI
# serves the SPA in prod), so SameSite=Lax is sufficient CSRF protection.
AUTH_COOKIE_NAME: str = "payout_token"
# Secure cookies require HTTPS; disable on localhost http dev. Set
# PAYOUT_COOKIE_SECURE=true in production (see render.yaml).
COOKIE_SECURE: bool = os.environ.get("PAYOUT_COOKIE_SECURE", "false").lower() in (
    "1", "true", "yes",
)
COOKIE_SAMESITE: str = "lax"
COOKIE_MAX_AGE: int = int(ACCESS_TOKEN_EXPIRES.total_seconds())
