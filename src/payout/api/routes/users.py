"""User management — list, create, change role, deactivate.

Role hierarchy:
  creator  > admin > recruiter > user
A creator can do everything an admin can, plus change other users' roles
and deactivate / reactivate accounts. A creator can never be deactivated
through the API; that's an explicit safeguard so you can't lock yourself
out by mistake.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from payout.api.auth import VALID_ROLES, get_current_user, require_creator
from payout.auth import hash_password
from payout.db import get_connection

router = APIRouter()


_VALID_ROLES = VALID_ROLES


class UserOut(BaseModel):
    email: str
    role: str
    is_active: bool
    phone: str | None = None
    created_at: str | None = None


class UserCreateIn(BaseModel):
    email: str
    password: str
    role: str = "user"
    phone: str | None = None


class PhoneIn(BaseModel):
    phone: str | None = None  # blank / null clears it


def _phone_or_400(raw: str | None) -> str | None:
    from payout.auth.phone import normalize_phone

    if raw is None or not raw.strip():
        return None
    p = normalize_phone(raw)
    if p is None:
        raise HTTPException(
            400, "That does not look like a phone number (10 digits, or +country code)."
        )
    return p


def _phone_taken(conn, phone: str, except_email: str | None = None) -> bool:
    row = conn.execute("SELECT email FROM users WHERE phone=?", (phone,)).fetchone()
    return bool(row) and row["email"] != except_email


class RoleChangeIn(BaseModel):
    role: str


def visible_role(role: str, viewer: dict) -> str:
    """The role as a given viewer is allowed to see it. The creator role is
    invisible below creator level: everyone else sees creators as plain
    admins, so admins and users have no idea the tier exists."""
    if role == "creator" and viewer.get("role") != "creator":
        return "admin"
    return role


@router.get("", response_model=list[UserOut])
def list_users(user: dict = Depends(get_current_user)) -> list[UserOut]:
    """Everyone who's signed in can see who else has access — useful when
    multiple operators are sharing the system. Creators appear as admins to
    anyone who is not one."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT email, role, is_active, phone, created_at FROM users ORDER BY email"
        ).fetchall()
    return [
        UserOut(
            email=r["email"],
            role=visible_role(r["role"], user),
            is_active=bool(r["is_active"]),
            phone=r["phone"],
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreateIn, _: dict = Depends(require_creator)) -> UserOut:
    if body.role not in _VALID_ROLES:
        raise HTTPException(400, f"role must be one of {_VALID_ROLES}")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    email = body.email.strip().lower()
    phone = _phone_or_400(body.phone)
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(409, "That email already has an account.")
        if phone and _phone_taken(conn, phone):
            raise HTTPException(409, "That phone number is already on another account.")
        conn.execute(
            "INSERT INTO users (email, password_hash, role, phone) VALUES (?,?,?,?)",
            (email, hash_password(body.password), body.role, phone),
        )
        conn.commit()
    return UserOut(email=email, role=body.role, is_active=True, phone=phone)


@router.patch("/{email}/phone")
def set_phone(email: str, body: PhoneIn, _: dict = Depends(require_creator)) -> dict:
    """Creator sets (or clears) a user's phone number — their second login id."""
    target = email.strip().lower()
    phone = _phone_or_400(body.phone)
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE email=?", (target,)).fetchone():
            raise HTTPException(404, "User not found")
        if phone and _phone_taken(conn, phone, except_email=target):
            raise HTTPException(409, "That phone number is already on another account.")
        conn.execute("UPDATE users SET phone=? WHERE email=?", (phone, target))
        conn.commit()
    return {"email": target, "phone": phone}


@router.patch("/{email}/role")
def change_role(email: str, body: RoleChangeIn, user: dict = Depends(require_creator)) -> dict:
    if body.role not in _VALID_ROLES:
        raise HTTPException(400, f"role must be one of {_VALID_ROLES}")
    target = email.strip().lower()
    if target == user["email"] and body.role != "creator":
        raise HTTPException(
            400,
            "You can't demote yourself — promote a different user to creator first.",
        )
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE email=?", (target,)).fetchone():
            raise HTTPException(404, "User not found")
        conn.execute("UPDATE users SET role=? WHERE email=?", (body.role, target))
        conn.commit()
    return {"email": target, "role": body.role}


class PasswordSetIn(BaseModel):
    new_password: str


@router.patch("/{email}/password")
def set_password(email: str, body: PasswordSetIn, user: dict = Depends(require_creator)) -> dict:
    """Creator sets another user's password (no email round-trip needed).

    This is the "ask an administrator" path the forgot-password screen points
    to when SMTP is not configured. Any live reset codes for the user are
    invalidated so an old OTP cannot undo the new password."""
    target = email.strip().lower()
    if len(body.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE email=?", (target,)).fetchone():
            raise HTTPException(404, "User not found")
        conn.execute(
            "UPDATE users SET password_hash=? WHERE email=?",
            (hash_password(body.new_password), target),
        )
        conn.execute(
            "UPDATE password_reset_tokens SET used_at=datetime('now') "
            "WHERE email=? AND used_at IS NULL",
            (target,),
        )
        conn.commit()
    return {"email": target, "password_set": True, "by": user["email"]}


@router.patch("/{email}/deactivate")
def deactivate(email: str, user: dict = Depends(require_creator)) -> dict:
    target = email.strip().lower()
    if target == user["email"]:
        raise HTTPException(400, "You can't deactivate yourself.")
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE email=?", (target,)).fetchone():
            raise HTTPException(404, "User not found")
        conn.execute("UPDATE users SET is_active=0 WHERE email=?", (target,))
        conn.commit()
    return {"email": target, "is_active": False}


@router.patch("/{email}/reactivate")
def reactivate(email: str, _: dict = Depends(require_creator)) -> dict:
    target = email.strip().lower()
    with get_connection() as conn:
        if not conn.execute("SELECT 1 FROM users WHERE email=?", (target,)).fetchone():
            raise HTTPException(404, "User not found")
        conn.execute("UPDATE users SET is_active=1 WHERE email=?", (target,))
        conn.commit()
    return {"email": target, "is_active": True}
