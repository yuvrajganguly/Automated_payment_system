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

from payout.api.auth import (
    VALID_ROLES,
    get_current_user,
    require_admin,
    require_admin_over,
    require_creator,
)
from payout.api.routes.hubs import ZONES
from payout.auth import hash_password
from payout.auth.sessions import revoke_all
from payout.db import get_connection

router = APIRouter()


_VALID_ROLES = VALID_ROLES


class UserOut(BaseModel):
    email: str
    role: str
    is_active: bool
    phone: str | None = None
    zone: str | None = None  # North | South — the recruiter's patch
    # Head recruiter for that zone: supervises the field staff in it. A flag,
    # not a rank — they stay a recruiter for every permission check.
    is_head: bool = False
    created_at: str | None = None


class ZoneIn(BaseModel):
    zone: str | None = None


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
            "SELECT email, role, is_active, phone, zone, is_head, created_at "
            "FROM users ORDER BY email"
        ).fetchall()
    return [
        UserOut(
            email=r["email"],
            role=visible_role(r["role"], user),
            is_active=bool(r["is_active"]),
            phone=r["phone"],
            zone=r["zone"],
            is_head=bool(r["is_head"]),
            created_at=r["created_at"],
        )
        for r in rows
    ]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreateIn, user: dict = Depends(require_admin)) -> UserOut:
    """Make an account. An admin can create recruiters and plain users — the
    accounts they actually have to hand out. Creating another admin, or a
    creator, stays with the creator: an admin who could mint an admin could
    escalate their own privilege by proxy."""
    if body.role not in _VALID_ROLES:
        raise HTTPException(400, f"role must be one of {_VALID_ROLES}")
    require_admin_over(user, body.role)
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
def set_phone(email: str, body: PhoneIn, user: dict = Depends(require_admin)) -> dict:
    """Set (or clear) a user's phone number — their second login id.

    Rank-guarded like the rest: the phone is one of the two identifiers an
    account can sign in with, so taking one off a colleague's account is a
    lock-out an admin should not be able to perform.
    """
    target = email.strip().lower()
    phone = _phone_or_400(body.phone)
    with get_connection() as conn:
        row = conn.execute("SELECT role FROM users WHERE email=?", (target,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        require_admin_over(user, row["role"])
        if phone and _phone_taken(conn, phone, except_email=target):
            raise HTTPException(409, "That phone number is already on another account.")
        conn.execute("UPDATE users SET phone=? WHERE email=?", (phone, target))
        conn.commit()
    return {"email": target, "phone": phone}


@router.patch("/{email}/zone")
def set_zone(email: str, body: ZoneIn, user: dict = Depends(require_admin)) -> dict:
    """Admin sets (or clears) the zone a recruiter works — North or South.
    The app opens its to-do list on the stores of that zone.

    Rank-guarded like every other write here. Zone is not cosmetic: the rider
    list falls back to the recruiter's zone for hub-less riders, so writing it
    onto a colleague's account moves data around on their screen.
    """
    target = email.strip().lower()
    zone = (body.zone or "").strip().title() or None
    if zone is not None and zone not in ZONES:
        raise HTTPException(400, f"zone must be one of {', '.join(ZONES)} (or empty to clear)")
    with get_connection() as conn:
        row = conn.execute("SELECT role FROM users WHERE email=?", (target,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        require_admin_over(user, row["role"])
        conn.execute("UPDATE users SET zone=? WHERE email=?", (zone, target))
        conn.commit()
    return {"email": target, "zone": zone}


class HeadIn(BaseModel):
    is_head: bool


@router.patch("/{email}/head")
def set_head(email: str, body: HeadIn, user: dict = Depends(require_admin)) -> dict:
    """Make a recruiter the head of their zone, or stand them down.

    Only a recruiter can hold it: on an admin it would mean nothing (they see
    everything already) and on a plain user it would be a way to hand out
    roster sight without the role that comes with it. A head with no zone
    supervises nobody, so this refuses one rather than leaving a flag that
    silently does nothing — set the zone first.

    Rank-guarded like every other write here: this grants sight of colleagues'
    work, which is not something an admin should be able to hand to an account
    at or above their own rank.
    """
    target = email.strip().lower()
    with get_connection() as conn:
        row = conn.execute("SELECT role, zone FROM users WHERE email=?", (target,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        require_admin_over(user, row["role"])
        if body.is_head:
            if row["role"] != "recruiter":
                raise HTTPException(400, "Only a recruiter can be the head of a zone")
            if not (row["zone"] or "").strip():
                raise HTTPException(400, "Give them a zone first — a head with no zone sees nobody")
        conn.execute("UPDATE users SET is_head=? WHERE email=?", (1 if body.is_head else 0, target))
        conn.commit()
    return {"email": target, "is_head": body.is_head, "zone": row["zone"]}


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
def set_password(email: str, body: PasswordSetIn, user: dict = Depends(require_admin)) -> dict:
    """Set another user's password (no email round-trip needed).

    This is the "ask an administrator" path the forgot-password screen points
    to when SMTP is not configured. Any live reset codes for the user are
    invalidated so an old OTP cannot undo the new password.

    Setting a password is impersonation — whoever sets it can sign in as that
    person — so an admin may do it only for recruiters and plain users. Only a
    creator can set another admin's or a creator's password."""
    target = email.strip().lower()
    if len(body.new_password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    with get_connection() as conn:
        row = conn.execute("SELECT role FROM users WHERE email=?", (target,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        require_admin_over(user, row["role"])
        conn.execute(
            "UPDATE users SET password_hash=? WHERE email=?",
            (hash_password(body.new_password), target),
        )
        conn.execute(
            "UPDATE password_reset_tokens SET used_at=datetime('now') "
            "WHERE email=? AND used_at IS NULL",
            (target,),
        )
        revoke_all(conn, target, reason=f"password set by {user['email']}")
        conn.commit()
    return {"email": target, "password_set": True, "by": user["email"]}


@router.post("/{email}/sign-out-everywhere")
def sign_out_everywhere(email: str, user: dict = Depends(require_admin)) -> dict:
    """Revoke every app session of a user (lost phone). The web console's
    cookie still expires within 12 h; deactivate for an immediate lock-out."""
    target = email.strip().lower()
    with get_connection() as conn:
        row = conn.execute("SELECT role FROM users WHERE email=?", (target,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        require_admin_over(user, row["role"])
        n = revoke_all(conn, target, reason=f"signed out everywhere by {user['email']}")
        conn.commit()
    return {"email": target, "sessions_revoked": n}


@router.patch("/{email}/deactivate")
def deactivate(email: str, user: dict = Depends(require_admin)) -> dict:
    """Lock an account out. An admin may deactivate recruiters and plain
    users; locking out another admin, or a creator, stays with the creator."""
    target = email.strip().lower()
    if target == user["email"]:
        raise HTTPException(400, "You can't deactivate yourself.")
    with get_connection() as conn:
        row = conn.execute("SELECT role FROM users WHERE email=?", (target,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        require_admin_over(user, row["role"])
        conn.execute("UPDATE users SET is_active=0 WHERE email=?", (target,))
        revoke_all(conn, target, reason=f"deactivated by {user['email']}")
        conn.commit()
    return {"email": target, "is_active": False}


@router.patch("/{email}/reactivate")
def reactivate(email: str, user: dict = Depends(require_admin)) -> dict:
    """Let an account back in. Same rank rule as the rest, so the set of
    accounts an admin can act on is one rule, not five."""
    target = email.strip().lower()
    with get_connection() as conn:
        row = conn.execute("SELECT role FROM users WHERE email=?", (target,)).fetchone()
        if not row:
            raise HTTPException(404, "User not found")
        require_admin_over(user, row["role"])
        conn.execute("UPDATE users SET is_active=1 WHERE email=?", (target,))
        conn.commit()
    return {"email": target, "is_active": True}
