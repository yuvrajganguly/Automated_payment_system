"""User management — list, create, change role, deactivate.

Role hierarchy:
  creator  > admin > user
A creator can do everything an admin can, plus change other users' roles
and deactivate / reactivate accounts. A creator can never be deactivated
through the API; that's an explicit safeguard so you can't lock yourself
out by mistake.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from payout.api.auth import get_current_user, require_creator
from payout.auth import hash_password
from payout.db import get_connection

router = APIRouter()


_VALID_ROLES = ("user", "admin", "creator")


class UserOut(BaseModel):
    email: str
    role: str
    is_active: bool
    created_at: Optional[str] = None


class UserCreateIn(BaseModel):
    email: str
    password: str
    role: str = "user"


class RoleChangeIn(BaseModel):
    role: str


@router.get("", response_model=list[UserOut])
def list_users(_: dict = Depends(get_current_user)) -> list[UserOut]:
    """Everyone who's signed in can see who else has access — useful when
    multiple operators are sharing the system."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT email, role, is_active, created_at FROM users ORDER BY email"
        ).fetchall()
    return [
        UserOut(email=r["email"], role=r["role"],
                is_active=bool(r["is_active"]), created_at=r["created_at"])
        for r in rows
    ]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreateIn, _: dict = Depends(require_creator)) -> UserOut:
    if body.role not in _VALID_ROLES:
        raise HTTPException(400, f"role must be one of {_VALID_ROLES}")
    if len(body.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters")
    email = body.email.strip().lower()
    with get_connection() as conn:
        if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
            raise HTTPException(409, "That email already has an account.")
        conn.execute(
            "INSERT INTO users (email, password_hash, role) VALUES (?,?,?)",
            (email, hash_password(body.password), body.role),
        )
        conn.commit()
    return UserOut(email=email, role=body.role, is_active=True)


@router.patch("/{email}/role")
def change_role(email: str, body: RoleChangeIn,
                user: dict = Depends(require_creator)) -> dict:
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
