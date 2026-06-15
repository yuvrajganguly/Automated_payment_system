"""API configuration (JWT secret, CORS, token expiry)."""

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
