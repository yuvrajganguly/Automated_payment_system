"""Long-lived sessions for the recruiter app: refresh tokens.

The web console lives on a 12-hour JWT in an httpOnly cookie and simply
signs in again the next day. A phone must not ask for a password every
morning, so an app login also gets a *refresh token*: a random secret the
app keeps in encrypted storage and trades for a new access token whenever
the old one expires.

Rules:
* Only the SHA-256 of the token is stored; the value itself is shown once.
* Each use rotates it: the old token is marked replaced, a new one issued.
  Presenting a token that was already rotated is treated as theft — every
  session of that account is revoked and the user signs in again.
* Tokens expire after REFRESH_TOKEN_DAYS regardless of use.
* A password change, a creator "set password", a deactivation or an explicit
  logout revokes; the role and is_active are re-read on every request as
  before, so revocation is belt and braces.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

REFRESH_TOKEN_DAYS = 30
_PREFIX = "qrt_"  # marks the token kind in logs / bug reports without leaking it


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_refresh_token(conn, email: str, client: str | None) -> str:
    """Create a refresh token for ``email`` and return its plain value."""
    token = _PREFIX + secrets.token_urlsafe(32)
    expires = _now() + timedelta(days=REFRESH_TOKEN_DAYS)
    conn.execute(
        "INSERT INTO refresh_tokens (token_hash, email, client, expires_at) VALUES (?,?,?,?)",
        (_hash(token), email, (client or "")[:80] or None, expires.isoformat(timespec="seconds")),
    )
    return token


class RefreshError(Exception):
    """The presented refresh token cannot be used; the message says why."""


def rotate_refresh_token(conn, token: str) -> tuple[str, str, str | None]:
    """Validate ``token``, retire it and issue its successor.

    Returns ``(email, new_token, client)``. Raises RefreshError when the
    token is unknown, expired, revoked, or — the dangerous case — already
    rotated once (then every session of the account is revoked)."""
    row = conn.execute(
        "SELECT id, email, client, expires_at, revoked_at, replaced_by "
        "FROM refresh_tokens WHERE token_hash=?",
        (_hash(token or ""),),
    ).fetchone()
    if not row:
        raise RefreshError("Session not recognised — sign in again.")
    if row["replaced_by"] is not None:
        # Reuse of a rotated token: someone else holds a copy. Cut every
        # session for this account so both parties must sign in afresh.
        revoke_all(conn, row["email"], reason="refresh token reused")
        raise RefreshError("This session was used from elsewhere — sign in again.")
    if row["revoked_at"] is not None:
        raise RefreshError("Session signed out — sign in again.")
    try:
        expires = datetime.fromisoformat(row["expires_at"])
    except (TypeError, ValueError):
        expires = _now() - timedelta(seconds=1)
    if expires < _now():
        raise RefreshError("Session expired — sign in again.")
    user = conn.execute("SELECT is_active FROM users WHERE email=?", (row["email"],)).fetchone()
    if not user or not user["is_active"]:
        raise RefreshError("Account is disabled or no longer exists")
    new_token = issue_refresh_token(conn, row["email"], row["client"])
    new_id = conn.execute(
        "SELECT id FROM refresh_tokens WHERE token_hash=?", (_hash(new_token),)
    ).fetchone()["id"]
    conn.execute(
        "UPDATE refresh_tokens SET replaced_by=?, revoked_at=?, last_used_at=? WHERE id=?",
        (
            new_id,
            _now().isoformat(timespec="seconds"),
            _now().isoformat(timespec="seconds"),
            row["id"],
        ),
    )
    return row["email"], new_token, row["client"]


def revoke_refresh_token(conn, token: str) -> bool:
    """Revoke one token (logout from this phone). Returns True if it existed."""
    cur = conn.execute(
        "UPDATE refresh_tokens SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
        (_now().isoformat(timespec="seconds"), _hash(token or "")),
    )
    return (cur.rowcount or 0) > 0


def revoke_all(conn, email: str, *, reason: str | None = None) -> int:
    """Revoke every live refresh token of ``email`` (password change,
    deactivation, sign-out-everywhere). Returns how many were live."""
    cur = conn.execute(
        "UPDATE refresh_tokens SET revoked_at=?, revoke_reason=? "
        "WHERE email=? AND revoked_at IS NULL",
        (_now().isoformat(timespec="seconds"), reason, email),
    )
    return cur.rowcount or 0


def live_sessions(conn, email: str) -> list[dict]:
    """The account's open sessions (for a "signed in on" list)."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT id, client, created_at, last_used_at, expires_at FROM refresh_tokens "
            "WHERE email=? AND revoked_at IS NULL AND expires_at > ? ORDER BY created_at DESC",
            (email, _now().isoformat(timespec="seconds")),
        )
    ]
