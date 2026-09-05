"""Aadhaar / PAN numbers as stored on a person: normalised, format-checked.

Only the numbers are kept (no scans). Aadhaar is 12 digits; the Verhoeff
checksum is deliberately not enforced — a typo is the operator's to fix and
a false "invalid" on a real number would be worse than a stored typo.
"""

from __future__ import annotations

import re

_PAN = re.compile(r"^[A-Z]{5}[0-9]{4}[A-Z]$")


def normalize_aadhaar(raw: str | None) -> str | None:
    """12 digits with spaces/dashes removed; None for blank; ValueError otherwise."""
    if raw is None:
        return None
    digits = re.sub(r"[\s-]", "", raw.strip())
    if not digits:
        return None
    if not (digits.isdigit() and len(digits) == 12):
        raise ValueError("Aadhaar must be 12 digits")
    return digits


def normalize_pan(raw: str | None) -> str | None:
    """Upper-cased AAAAA9999A; None for blank; ValueError otherwise."""
    if raw is None:
        return None
    pan = re.sub(r"\s", "", raw.strip()).upper()
    if not pan:
        return None
    if not _PAN.match(pan):
        raise ValueError("PAN must look like ABCDE1234F")
    return pan


def format_aadhaar(value: str | None) -> str | None:
    """1234 5678 9012 for display."""
    if not value:
        return None
    return " ".join(value[i : i + 4] for i in range(0, len(value), 4))
