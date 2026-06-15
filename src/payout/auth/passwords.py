"""Password hashing and verification using bcrypt.

Kept free of any framework or database dependency so it is trivially unit
testable. This replaces the previous unsalted SHA-256 placeholder.
"""

from __future__ import annotations

import bcrypt


def hash_password(password: str) -> str:
    """Return a salted bcrypt hash for ``password`` (safe to store)."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, stored_hash: str) -> bool:
    """Return True if ``password`` matches ``stored_hash``.

    Returns False (rather than raising) for empty or malformed hashes, so a
    corrupt record can never accidentally authenticate or crash the login flow.
    """
    if not stored_hash:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False
