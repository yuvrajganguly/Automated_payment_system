"""Auth routes: login (JWT), current user, and change password."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm

from payout.api.auth import authenticate, create_access_token, get_current_user
from payout.api.schemas import ChangePasswordIn, TokenOut, UserOut
from payout.auth import hash_password
from payout.db import get_connection

router = APIRouter()


@router.post("/login", response_model=TokenOut)
def login(form_data: OAuth2PasswordRequestForm = Depends()) -> TokenOut:
    """Standard OAuth2 password flow. `username` is the user's email."""
    user = authenticate(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return TokenOut(
        access_token=create_access_token(subject=user["email"], role=user["role"]),
        role=user["role"], email=user["email"],
    )


@router.get("/me", response_model=UserOut)
def me(user: dict = Depends(get_current_user)) -> UserOut:
    return UserOut(**user)


@router.post("/change-password")
def change_password(body: ChangePasswordIn,
                    user: dict = Depends(get_current_user)) -> dict:
    if len(body.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters")
    if not authenticate(user["email"], body.current_password):
        raise HTTPException(401, "Current password is incorrect")
    with get_connection() as conn:
        conn.execute("UPDATE users SET password_hash=? WHERE email=?",
                     (hash_password(body.new_password), user["email"]))
        conn.commit()
    return {"ok": True}
