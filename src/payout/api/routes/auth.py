"""Auth routes: login (JWT), current user, change password, OTP reset."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from payout.api.auth import authenticate, create_access_token, get_current_user
from payout.api.schemas import ChangePasswordIn, TokenOut, UserOut
from payout.auth import hash_password
from payout.db import get_connection
from payout.notifications import send_email

router = APIRouter()


# ── OTP password reset ─────────────────────────────────────────────────────
OTP_TTL_MINUTES = 10


class ForgotPasswordIn(BaseModel):
    email: str


class ResetPasswordIn(BaseModel):
    email: str
    otp: str
    new_password: str


def _hash_otp(otp: str) -> str:
    return bcrypt.hashpw(otp.encode(), bcrypt.gensalt()).decode()


def _verify_otp(otp: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(otp.encode(), stored_hash.encode())
    except Exception:
        return False


@router.post("/forgot-password")
def forgot_password(body: ForgotPasswordIn) -> dict:
    """Generate a single-use 6-digit OTP and email it to the user.

    For privacy we return the same response whether or not the email is
    registered — don't leak which addresses have accounts."""
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(400, "Email is required")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT email FROM users WHERE email=? AND is_active=1", (email,)
        ).fetchone()
        if row:
            otp = f