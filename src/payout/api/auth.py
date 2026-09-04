"""JWT authentication helpers and FastAPI dependencies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from payout.api.config import (
    ACCESS_TOKEN_EXPIRES,
    AUTH_COOKIE_NAME,
    COOKIE_MAX_AGE,
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    JWT_ALGORITHM,
    JWT_SECRET,
)
from payout.auth import verify_password
from payout.db import get_connection

# auto_error=False: a missing Authorization header is not an error on its own —
# the token may instead arrive in the httpOnly auth cookie (see get_current_user).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


def set_auth_cookie(response: Response, token: str) -> None:
    """Attach the JWT as an httpOnly cookie on ``response``."""
    response.set_cookie(
        key=AUTH_COOKIE_NAME,
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Remove the auth cookie (logout). Flags must match set_auth_cookie."""
    response.delete_cookie(
        key=AUTH_COOKIE_NAME,
        httponly=True,
        secure=COOKIE_SECURE,
        samesite=COOKIE_SAMESITE,
        path="/",
    )


def create_access_token(subject: str, role: str, expires: timedelta | None = None) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "role": role,
        "iat": now,
        "exp": now + (expires or ACCESS_TOKEN_EXPIRES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def authenticate(email: str, password: str) -> dict | None:
    """Verify credentials against the users table (bcrypt)."""
    email = email.strip().lower()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT email, password_hash, role FROM users WHERE email=? AND is_active=1",
            (email,),
        ).fetchone()
    if row and verify_password(password, row["password_hash"]):
        return {"email": row["email"], "role": row["role"]}
    return None


def _load_user(email: str) -> dict | None:
    """Current DB state for ``email`` — the JWT is only a session hint.

    A token is valid for 12 hours, so without this lookup deactivating or
    demoting a user would have no effect until it expired. One primary-key
    read per request is a price worth paying for that.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT email, role, is_active FROM users WHERE email=?", (email,)
        ).fetchone()
    if not row:
        return None
    return {"email": row["email"], "role": row["role"], "is_active": bool(row["is_active"])}


def get_current_user(
    request: Request,
    header_token: str | None = Depends(oauth2_scheme),
) -> dict:
    """Resolve the caller from the JWT, taken from the Authorization header
    (API/script clients) or the httpOnly auth cookie (browser), then confirm
    the account still exists and is active. The role comes from the database,
    not the token, so a role change takes effect on the next request."""
    token = header_token or request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_token(token)
    if not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")
    user = _load_user(payload["sub"])
    if user is None or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is disabled or no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return {"email": user["email"], "role": user["role"]}


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Allow admin AND creator (creator is a strict super-set of admin)."""
    if user.get("role") not in ("admin", "creator"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def require_creator(user: dict = Depends(get_current_user)) -> dict:
    """Only the creator (super-admin) can change roles or remove other users.

    The refusal is deliberately generic: nobody below creator is told the
    role exists."""
    if user.get("role") != "creator":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")
    return user
