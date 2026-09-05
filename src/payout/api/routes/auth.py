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
from payout.notifications import (
    email_configured,
    send_email,
    send_whatsapp_otp,
    whatsapp_configured,
)

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
    email: str  # email address OR phone number (kept as "email" for old clients)
    channel: str | None = None  # "email" | "whatsapp" | None = best available


class OtpSendIn(BaseModel):
    phone: str


class OtpLoginIn(BaseModel):
    phone: str
    otp: str


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


def _issue_otp(conn, email: str) -> str:
    """Create a fresh single-use code for ``email``, retiring any earlier one."""
    otp = f"{secrets.randbelow(1_000_000):06d}"
    expires_at = (datetime.utcnow() + timedelta(minutes=OTP_TTL_MINUTES)).isoformat()
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
    return otp


def _verify_otp_for(conn, email: str, otp: str) -> None:
    """Check ``otp`` against the live code for ``email``; burn it on success.
    Raises the same neutral HTTP errors the reset flow always used."""
    token = conn.execute(
        "SELECT id, otp_hash, expires_at, attempts FROM password_reset_tokens "
        "WHERE email=? AND used_at IS NULL ORDER BY id DESC LIMIT 1",
        (email,),
    ).fetchone()
    if not token:
        raise HTTPException(400, "This code is not valid. Request a new one.")
    try:
        expires_at = datetime.fromisoformat(token["expires_at"])
    except Exception:
        expires_at = datetime.utcnow() - timedelta(seconds=1)
    if datetime.utcnow() > expires_at:
        conn.execute(
            "UPDATE password_reset_tokens SET used_at=datetime('now') WHERE id=?", (token["id"],)
        )
        conn.commit()
        raise HTTPException(400, "This code is not valid. Request a new one.")
    if not _verify_otp(otp, token["otp_hash"]):
        attempts = int(token["attempts"] or 0) + 1
        if attempts >= MAX_OTP_ATTEMPTS:
            conn.execute(
                "UPDATE password_reset_tokens SET attempts=?, used_at=datetime('now') WHERE id=?",
                (attempts, token["id"]),
            )
            conn.commit()
            raise HTTPException(401, "Too many incorrect codes. Request a new one to try again.")
        conn.execute(
            "UPDATE password_reset_tokens SET attempts=? WHERE id=?", (attempts, token["id"])
        )
        conn.commit()
        raise HTTPException(401, "Incorrect code.")
    conn.execute(
        "UPDATE password_reset_tokens SET used_at=datetime('now') WHERE id=?", (token["id"],)
    )


@router.post("/forgot-password", dependencies=[Depends(_forgot_limit)])
def forgot_password(body: ForgotPasswordIn) -> dict:
    """Send a single-use 6-digit code to the account behind ``email`` (an email
    address or a phone number) — on WhatsApp when the account has a phone and
    WhatsApp is configured, else by email. ``channel`` forces one.

    For privacy the answer is the same whether or not the account exists."""
    from payout.auth.phone import looks_like_phone, normalize_phone

    ident = body.email.strip()
    if not ident:
        raise HTTPException(400, "Email or phone number is required")
    want = (body.channel or "").strip().lower() or None
    if want not in (None, "email", "whatsapp"):
        raise HTTPException(400, "channel must be 'email' or 'whatsapp'")
    if not email_configured() and not whatsapp_configured():
        raise HTTPException(
            503,
            "Password reset by email or WhatsApp is not set up on this server. "
            "Ask the account owner to set a new password for you "
            "(Users page → Set password).",
        )
    with get_connection() as conn:
        if looks_like_phone(ident):
            row = conn.execute(
                "SELECT email, phone FROM users WHERE phone=? AND is_active=1",
                (normalize_phone(ident),),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT email, phone FROM users WHERE email=? AND is_active=1",
                (ident.lower(),),
            ).fetchone()
        # Decide the channel for the neutral message even when no account.
        via_whatsapp = (
            whatsapp_configured()
            and want != "email"
            and (
                (row is not None and bool(row["phone"]))
                or (row is None and looks_like_phone(ident))
            )
        )
        if want == "whatsapp" and not whatsapp_configured():
            raise HTTPException(503, "WhatsApp codes are not set up on this server.")
        if via_whatsapp and row is not None and not row["phone"]:
            via_whatsapp = False
        if not via_whatsapp and not email_configured():
            # Only WhatsApp is configured and this account has no phone.
            raise HTTPException(
                503,
                "This account has no phone number for WhatsApp codes and email "
                "reset is not set up. Ask the account owner to set a password.",
            )
        if row:
            otp = _issue_otp(conn, row["email"])
            if via_whatsapp:
                if not send_whatsapp_otp(row["phone"], otp):
                    raise HTTPException(503, "Could not send the WhatsApp code. Try again later.")
            else:
                body_text = (
                    f"Hi,\n\nYour Payout System password-reset code is:\n\n    {otp}\n\n"
                    f"It expires in {OTP_TTL_MINUTES} minutes. If you didn't request a "
                    f"reset, ignore this email — nothing has changed.\n"
                )
                if not send_email(row["email"], "Payout System — password reset code", body_text):
                    raise HTTPException(503, "Could not send the reset email. Try again later.")
    channel = "whatsapp" if via_whatsapp else "email"
    return {
        "ok": True,
        "channel": channel,
        "message": (
            "If that account exists, a code has been sent on WhatsApp."
            if via_whatsapp
            else "If that account exists, a code has been emailed to it."
        ),
    }


@router.post("/otp/send", dependencies=[Depends(_forgot_limit)])
def otp_send(body: OtpSendIn) -> dict:
    """Passwordless sign-in, step 1: a WhatsApp code to a registered phone.
    Same neutral answer for unknown numbers."""
    from payout.auth.phone import normalize_phone

    phone = normalize_phone(body.phone)
    if not phone:
        raise HTTPException(400, "That does not look like a phone number.")
    if not whatsapp_configured():
        raise HTTPException(503, "WhatsApp codes are not set up on this server.")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT email FROM users WHERE phone=? AND is_active=1", (phone,)
        ).fetchone()
        if row:
            otp = _issue_otp(conn, row["email"])
            if not send_whatsapp_otp(phone, otp):
                raise HTTPException(503, "Could not send the WhatsApp code. Try again later.")
    return {
        "ok": True,
        "message": "If that number is registered, a code has been sent on WhatsApp.",
    }


@router.post("/otp/login", response_model=TokenOut, dependencies=[Depends(_reset_limit)])
def otp_login(body: OtpLoginIn, response: Response) -> TokenOut:
    """Passwordless sign-in, step 2: the code from WhatsApp signs the user in."""
    from payout.auth.phone import normalize_phone

    phone = normalize_phone(body.phone)
    otp = body.otp.strip()
    if not phone or not otp:
        raise HTTPException(400, "Phone number and code are required")
    with get_connection() as conn:
        row = conn.execute(
            "SELECT email, role FROM users WHERE phone=? AND is_active=1", (phone,)
        ).fetchone()
        if not row:
            raise HTTPException(400, "This code is not valid. Request a new one.")
        _verify_otp_for(conn, row["email"], otp)
        conn.commit()
    token = create_access_token(subject=row["email"], role=row["role"])
    set_auth_cookie(response, token)
    return TokenOut(access_token=token, role=row["role"], email=row["email"])


@router.post("/reset-password", dependencies=[Depends(_reset_limit)])
def reset_password(body: ResetPasswordIn) -> dict:
    """Validate the OTP (sent by email or WhatsApp) and set a new password.
    ``email`` may be the phone number the code was requested with."""
    from payout.auth.phone import looks_like_phone, normalize_phone

    ident = body.email.strip()
    otp = body.otp.strip()
    if not ident or not otp:
        raise HTTPException(400, "Email and OTP are required")
    if len(body.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")

    with get_connection() as conn:
        if looks_like_phone(ident):
            row = conn.execute(
                "SELECT email FROM users WHERE phone=? AND is_active=1",
                (normalize_phone(ident),),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT email FROM users WHERE email=? AND is_active=1", (ident.lower(),)
            ).fetchone()
        if not row:
            # One message for "no request", "expired" and "user missing" so the
            # endpoint doesn't confirm which addresses have accounts.
            raise HTTPException(400, "This code is not valid. Request a new one.")
        email = row["email"]
        _verify_otp_for(conn, email, otp)
        conn.execute(
            "UPDATE users SET password_hash=? WHERE email=?",
            (hash_password(body.new_password), email),
        )
        conn.commit()
    return {"ok": True, "message": "Password updated. You can sign in now."}


@router.post("/login", response_model=TokenOut, dependencies=[Depends(_login_limit)])
def login(response: Response, form_data: OAuth2PasswordRequestForm = Depends()) -> TokenOut:
    """Standard OAuth2 password flow. `username` is the user's email or phone.

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


class PhoneSelfIn(BaseModel):
    phone: str | None = None


@router.patch("/me/phone")
def set_my_phone(body: PhoneSelfIn, user: dict = Depends(get_current_user)) -> dict:
    """Set or clear your own phone number (second login id)."""
    from payout.auth.phone import normalize_phone

    raw = (body.phone or "").strip()
    phone = None
    if raw:
        phone = normalize_phone(raw)
        if phone is None:
            raise HTTPException(
                400, "That does not look like a phone number (10 digits, or +country code)."
            )
    with get_connection() as conn:
        if phone:
            other = conn.execute("SELECT email FROM users WHERE phone=?", (phone,)).fetchone()
            if other and other["email"] != user["email"]:
                raise HTTPException(409, "That phone number is already on another account.")
        conn.execute("UPDATE users SET phone=? WHERE email=?", (phone, user["email"]))
        conn.commit()
    return {"email": user["email"], "phone": phone}


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
