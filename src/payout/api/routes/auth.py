"""Auth routes: login (JWT), current user, change password, OTP reset."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta

import bcrypt
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from payout.api.auth import (
    authenticate,
    clear_auth_cookie,
    create_access_token,
    get_current_user,
    set_auth_cookie,
)
from payout.api.ratelimit import rate_limit
from payout.api.schemas import ChangePasswordIn, TokenOut, UserOut
from payout.auth import hash_password
from payout.db import get_connection
from payout.notifications import email_configured, send_email

router = APIRouter()


# ── OTP password reset ─────────────────────────────────────────────────────
OTP_TTL_MINUTES = 10
# A 6-digit code has a 1-in-1,000,000 chance per guess; five guesses keeps the
# odds of a lucky hit at 0.0005% and the code is then dead until re-issued.
MAX_OTP_ATTEMPTS = 5

# Per-client-IP limits on the unauthenticated routes. Generous for a human,
# fatal for a script. bcrypt makes each login/OTP check ~100 ms of CPU, so
# these also protect the single-process server from being wedged.
_login_limit = rate_limit("login", limit=20, window_seconds=60)
_forgot_limit = rate_limit("forgot-password", limit=5, window_seconds=15 * 60)
_reset_limit = rate_limit("reset-password", limit=10, window_seconds=15 * 60)


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


@router.post("/forgot-password", dependencies=[Depends(_forgot_limit)])
def forgot_password(body: ForgotPasswordIn) -> dict:
    """Generate a single-use 6-digit OTP and email it to the user.

    For privacy we return the same response whether or not the email is
    registered — don't leak which addresses have accounts."""
    email = body.email.strip().lower()
    if not email:
        raise HTTPException(400, "Email is required")
    if not email_configured():
        # Checked before the account lookup so the answer is identical for
        # registered and unregistered addresses. Previously the code was printed
        # to the server log and the user was told it had been sent.
        raise HTTPException(
            503,
            "Password reset by email is not set up on this server. "
            "Ask an administrator to reset your password.",
        )
    with get_connection() as conn:
        row = conn.execute(
            "SELECT email FROM users WHERE email=? AND is_active=1", (email,)
        ).fetchone()
        if row:
            otp = f"{secrets.randbelow(1_000_000):06d}"
            expires_at = (datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)).isoformat()
            # Invalidate any earlier unused tokens for this email.
            conn.execute(
                "UPDATE password_reset_tokens SET used_at=datetime('now') "
                "WHERE email=? AND used_at IS NULL",
                (email,),
            )
            conn.execute(
                "INSERT INTO password_reset_tokens (email, otp_hash, expires_at) VALUES (?,?,?)",
                (email, _hash_otp(otp), expires_at),
            )
            conn.commit()
            body_text = (
                f"Hi,\n\nYour Payout System password-reset code is:\n\n    {otp}\n\n"
                f"It expires in {OTP_TTL_MINUTES} minutes. If you didn't request a "
                f"reset, ignore this email — nothing has changed.\n"
            )
            if not send_email(email, "Payout System — password reset code", body_text):
                raise HTTPException(503, "Could not send the reset email. Try again later.")
    return {"ok": True, "message": "If that email is registered, a code has been sent."}


@router.post("/reset-password", dependencies=[Depends(_reset_limit)])
def reset_password(body: ResetPasswordIn) -> dict:
    """Validate the OTP and set a new password."""
    email = body.email.strip().lower()
    otp = body.otp.strip()
    if not email or not otp:
        raise HTTPException(400, "Email and OTP are required")
    if len(body.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")

    with get_connection() as conn:
        token = conn.execute(
            "SELECT id, otp_hash, expires_at, attempts FROM password_reset_tokens "
            "WHERE email=? AND used_at IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (email,),
        ).fetchone()
        if not token:
            # One message for "no request", "expired" and "user missing" so the
            # endpoint doesn't confirm which addresses have accounts.
            raise HTTPException(400, "This code is not valid. Request a new one.")
        # Expiry check.
        try:
            expires_at = datetime.fromisoformat(token["expires_at"])
        except Exception:
            expires_at = datetime.utcnow() - timedelta(seconds=1)
        if datetime.utcnow() > expires_at:
            conn.execute(
                "UPDATE password_reset_tokens SET used_at=datetime('now') WHERE id=?",
                (token["id"],),
            )
            conn.commit()
            raise HTTPException(400, "This code is not valid. Request a new one.")
        if not _verify_otp(otp, token["otp_hash"]):
            attempts = int(token["attempts"] or 0) + 1
            if attempts >= MAX_OTP_ATTEMPTS:
                # Burn the code: a wrong guess used to leave it live for more.
                conn.execute(
                    "UPDATE password_reset_tokens SET attempts=?, used_at=datetime('now') "
                    "WHERE id=?",
                    (attempts, token["id"]),
                )
                conn.commit()
                raise HTTPException(
                    401, "Too many incorrect codes. Request a new one to try again."
                )
            conn.execute(
                "UPDATE password_reset_tokens SET attempts=? WHERE id=?",
                (attempts, token["id"]),
            )
            conn.commit()
            raise HTTPException(401, "Incorrect code.")
        if not conn.execute(
            "SELECT 1 FROM users WHERE email=? AND is_active=1", (email,)
        ).fetchone():
            raise HTTPException(400, "This code is not valid. Request a new one.")
        conn.execute(
            "UPDATE users SET password_hash=? WHERE email=?",
            (hash_password(body.new_password), email),
        )
        conn.execute(
            "UPDATE password_reset_tokens SET used_at=datetime('now') WHERE id=?",
            (token["id"],),
        )
        conn.commit()
    return {"ok": True, "message": "Password updated. You can sign in now."}


@router.post("/login", response_model=TokenOut, dependencies=[Depends(_login_limit)])
def login(response: Response, form_data: OAuth2PasswordRequestForm = Depends()) -> TokenOut:
    """Standard OAuth2 password flow. `username` is the user's email.

    Sets the JWT as an httpOnly cookie for browser clients and also returns it
    in the body so API/script clients can use a Bearer header."""
    user = authenticate(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = create_access_token(subject=user["email"], role=user["role"])
    set_auth_cookie(response, token)
    return TokenOut(access_token=token, role=user["role"], email=user["email"])


@router.post("/logout")
def logout(response: Response) -> dict:
    """Clear the auth cookie. Safe to call even when not logged in."""
    clear_auth_cookie(response)
    return {"ok": True}


@router.get("/me", response_model=UserOut)
def me(user: dict = Depends(get_current_user)) -> UserOut:
    return UserOut(**user)


@router.post("/change-password")
def change_password(body: ChangePasswordIn, user: dict = Depends(get_current_user)) -> dict:
    if len(body.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    if not authenticate(user["email"], body.current_password):
        raise HTTPException(401, "Current password is incorrect")
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET password_hash=? WHERE email=?",
            (hash_password(body.new_password), user["email"]),
        )
        conn.commit()
    return {"ok": True}
