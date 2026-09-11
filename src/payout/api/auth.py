"""JWT authentication helpers and FastAPI dependencies."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jwt import InvalidTokenError

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
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def resolve_identifier(conn, identifier: str) -> dict | None:
    """The active user row for a login identifier — an email address or a
    phone number in any common Indian spelling (see auth.phone)."""
    from payout.auth.phone import looks_like_phone, normalize_phone

    ident = (identifier or "").strip()
    if not ident:
        return None
    if looks_like_phone(ident):
        return conn.execute(
            "SELECT email, password_hash, role, phone FROM users WHERE phone=? AND is_active=1",
            (normalize_phone(ident),),
        ).fetchone()
    return conn.execute(
        "SELECT email, password_hash, role, phone FROM users WHERE email=? AND is_active=1",
        (ident.lower(),),
    ).fetchone()


def authenticate(identifier: str, password: str) -> dict | None:
    """Verify credentials against the users table (bcrypt). ``identifier``
    is the email address or the phone number."""
    with get_connection() as conn:
        row = resolve_identifier(conn, identifier)
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
            "SELECT email, role, is_active, phone, zone, is_head FROM users WHERE email=?",
            (email,),
        ).fetchone()
    if not row:
        return None
    return {
        "email": row["email"],
        "role": row["role"],
        "is_active": bool(row["is_active"]),
        "phone": row["phone"],
        "zone": row["zone"],
        "is_head": bool(row["is_head"]),
    }


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
    return {
        "email": user["email"],
        "role": user["role"],
        "phone": user.get("phone"),
        "zone": user.get("zone"),
        # A head recruiter supervises their own zone. Deliberately NOT part of
        # ROLE_RANK: they are a recruiter everywhere a permission is checked,
        # including the money fence.
        "is_head": bool(user.get("is_head")),
    }


# Role ladder: creator > admin > recruiter > user.
#   user      read-only operator (money pages included)
#   recruiter field staff: onboard riders, hubs, bank details, documents, EVs
#             (add/assign/return/spare/maintenance). No money — they may only
#             REQUEST a credit/debit, which an admin decides.
#   admin     everything operational, incl. payouts and money
#   creator   admin + user management + system control (invisible below itself)
ROLE_RANK = {"user": 0, "recruiter": 1, "admin": 2, "creator": 3}
VALID_ROLES = tuple(ROLE_RANK)


def require_admin(user: dict = Depends(get_current_user)) -> dict:
    """Allow admin AND creator (creator is a strict super-set of admin)."""
    if user.get("role") not in ("admin", "creator"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


def require_recruiter(user: dict = Depends(get_current_user)) -> dict:
    """Recruiter, admin or creator — the roster/fleet write set."""
    if user.get("role") not in ("recruiter", "admin", "creator"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Recruiter access required"
        )
    return user


def heads_zone(user: dict) -> str | None:
    """The zone this caller supervises, lowercased, or None.

    A head recruiter with no zone supervises nothing — the flag is meaningless
    without a patch, and answering "everybody" would quietly hand a recruiter
    the whole company.
    """
    if not user.get("is_head"):
        return None
    if user.get("role") not in ("recruiter", "admin", "creator"):
        return None
    return ((user.get("zone") or "").strip().lower()) or None


def supervises(user: dict, target: dict | None) -> bool:
    """May this caller look at ``target``'s work?

    True for themselves, for an admin or creator looking at anyone, and for a
    head recruiter looking at a recruiter in their own zone. Everything that
    used to be admin-only supervision is widened by exactly this much.

    ``target`` is a users row (or dict) with ``email``, ``role`` and ``zone``.
    """
    if user.get("role") in ("admin", "creator"):
        return True
    if target is None:
        return False
    if (user.get("email") or "").lower() == (target.get("email") or "").lower():
        return True
    zone = heads_zone(user)
    if zone is None:
        return False
    # Field staff in their patch — not another head's account, and not
    # upwards. Two heads in one zone must not read each other.
    if target.get("is_head"):
        return False
    return target.get("role") == "recruiter" and (target.get("zone") or "").lower() == zone


def no_recruiter(user: dict = Depends(get_current_user)) -> dict:
    """Money-side routers are mounted with this: a recruiter sees riders and
    the fleet, never balances, payouts, arrears, COD or the ledger."""
    if user.get("role") == "recruiter":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")
    return user


def require_creator(user: dict = Depends(get_current_user)) -> dict:
    """Only the creator (super-admin).

    Since 2026-09 this guard covers a much smaller set than it used to. An
    admin now reaches the audit log, system stats, the EV model catalogue and
    most user administration, because an admin who cannot see what happened
    cannot do their job. What stays behind this guard is the two things an
    admin must not be able to do:

    * **Rewrite or erase history** — hard-deleting a person, an EV or a
      company, editing or voiding a posted ledger row, force-merging two
      people past the open-EV safety check.
    * **Escalate privilege** — changing anyone's role, or creating an account
      (which could mint another creator).

    The refusal is deliberately generic: nobody below creator is told the role
    exists."""
    if user.get("role") != "creator":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not permitted")
    return user


def require_admin_over(user: dict, target_role: str | None) -> None:
    """Refuse an admin acting on an account at or above their own rank.

    Setting someone's password is impersonation — whoever sets it can sign in
    as them. That is acceptable for an admin managing recruiters and plain
    users; it is not acceptable as a route by which an admin reaches a
    colleague's account or a creator's. A creator is not fenced: they are the
    top of the ladder and already hold every destructive route.
    """
    if user.get("role") == "creator":
        return
    if ROLE_RANK.get(target_role or "user", 0) >= ROLE_RANK["admin"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins can only act on recruiter and user accounts",
        )
