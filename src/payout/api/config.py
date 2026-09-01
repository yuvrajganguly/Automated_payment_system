"""API configuration (JWT secret, CORS, token expiry, auth cookie)."""

from __future__ import annotations

import os
from datetime import timedelta

_DEV_JWT_SECRET = "dev-secret-change-me-in-production"
_MIN_SECRET_LEN = 32
JWT_SECRET: str = os.environ.get("PAYOUT_JWT_SECRET", _DEV_JWT_SECRET)
JWT_ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRES: timedelta = timedelta(hours=12)


def _truthy(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


# Anyone who has read the source can forge an admin token when the app runs on
# the well-known dev secret, or brute-force a short one. Refuse to start unless
# the operator has *explicitly* opted into an insecure secret for local dev
# (PAYOUT_ALLOW_DEV_SECRET=1). This used to fire only when PAYOUT_COOKIE_SECURE
# was set, which left the stated use case — an internal HTTP deployment — on
# the dev secret whenever .env was missing.
ALLOW_DEV_SECRET: bool = _truthy("PAYOUT_ALLOW_DEV_SECRET")
_secret_is_weak = JWT_SECRET == _DEV_JWT_SECRET or len(JWT_SECRET) < _MIN_SECRET_LEN
if _secret_is_weak and not ALLOW_DEV_SECRET:
    raise RuntimeError(
        "PAYOUT_JWT_SECRET is unset or shorter than 32 characters. Generate one with\n"
        '  python -c "import secrets; print(secrets.token_hex(32))"\n'
        "and put it in .env (see .env.example). For throwaway local development only, "
        "set PAYOUT_ALLOW_DEV_SECRET=1."
    )
if _secret_is_weak and _truthy("PAYOUT_COOKIE_SECURE"):
    # Never allow the escape hatch on an HTTPS (production-looking) deployment.
    raise RuntimeError("PAYOUT_ALLOW_DEV_SECRET cannot be combined with PAYOUT_COOKIE_SECURE=true.")

# Demo accounts (admin@demo.com / Demo-1234) and the synthetic fleet exist for
# the public demo only. Opt-IN: a real deployment that forgets to set this gets
# no demo login. (It used to default on, and the demo admin ended up in prod.)
DEMO_MODE: bool = _truthy("PAYOUT_SEED_DEMO")

CORS_ORIGINS: list[str] = [
    o.strip()
    for o in os.environ.get(
        "PAYOUT_CORS_ORIGINS",
        "http://localhost:5173,http://localhost:3000,http://127.0.0.1:5173",
    ).split(",")
    if o.strip()
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
    "1",
    "true",
    "yes",
)
COOKIE_SAMESITE: str = "lax"
COOKIE_MAX_AGE: int = int(ACCESS_TOKEN_EXPIRES.total_seconds())
