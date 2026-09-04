"""Phone numbers as login identifiers.

Stored in E.164 (``+919876543210``). Indian numbers are the norm here, so a
bare 10-digit number, or one with a leading 0 / 91 / +91, all normalise to
the same value; anything else must carry its own country code with a +.
"""

from __future__ import annotations

import re

_DIGITS = re.compile(r"\d+")


def normalize_phone(raw: str | None) -> str | None:
    """E.164 form of ``raw``, or None when it is blank or not a phone number.

    >>> normalize_phone("98765 43210")
    '+919876543210'
    >>> normalize_phone("+91-98765-43210")
    '+919876543210'
    >>> normalize_phone("09876543210")
    '+919876543210'
    >>> normalize_phone("hello") is None
    True
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None
    plus = s.startswith("+")
    digits = "".join(_DIGITS.findall(s))
    if not digits:
        return None
    if plus:
        return "+" + digits if 8 <= len(digits) <= 15 else None
    if len(digits) == 10 and digits[0] in "6789":
        return "+91" + digits
    if len(digits) == 11 and digits[0] == "0" and digits[1] in "6789":
        return "+91" + digits[1:]
    if len(digits) == 12 and digits.startswith("91") and digits[2] in "6789":
        return "+" + digits
    return None


def looks_like_phone(identifier: str) -> bool:
    """True when a login identifier is a phone number rather than an email."""
    s = identifier.strip()
    return "@" not in s and normalize_phone(s) is not None
