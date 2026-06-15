"""JWT authentication helpers and FastAPI dependencies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from payout.api.config import ACCESS_TOKEN_EXPIRES, JWT_ALGORITHM, JWT_SECRET
from payout.auth import verify_password
from payout.db import get_connection

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def create_access_token(subject: str, role: str, expires: Optional[timedelta] = None) -> str:
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


def authenticate(email: str, password: str) -> Optional[dict]:
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


def get_current_user(token: str = Depends(oauth2_scheme)) -> dict:
    payload = decode_token(token)
    if not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Malformed token")
    return {"email": payload["sub"], "role": payload.get("role", "user")}


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user
