"""Thin email layer.

Reads SMTP config from environment variables. If any are missing, falls back
to logging the message to stdout — useful for solo dev and avoids hard-failing
when no mail service is wired up yet.

Required env vars for live send:
    PAYOUT_SMTP_HOST       (e.g. smtp.gmail.com)
    PAYOUT_SMTP_PORT       (e.g. 587)
    PAYOUT_SMTP_USER       (login email)
    PAYOUT_SMTP_PASS       (app password)
    PAYOUT_SMTP_FROM       (sender address, defaults to PAYOUT_SMTP_USER)
"""

from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def _smtp_settings() -> tuple[str | None, str | None, str | None, str | None, str | None]:
    host = os.environ.get("PAYOUT_SMTP_HOST")
    port = os.environ.get("PAYOUT_SMTP_PORT")
    user = os.environ.get("PAYOUT_SMTP_USER")
    pwd = os.environ.get("PAYOUT_SMTP_PASS")
    sender = os.environ.get("PAYOUT_SMTP_FROM") or user
    return host, port, user, pwd, sender


def email_configured() -> bool:
    """True when live SMTP is set up, or when the dev console sink is enabled
    explicitly with PAYOUT_DEV_PRINT_EMAIL=1 (never on by default: the body of a
    reset email IS the one-time code, and server logs are not a safe place for it)."""
    host, port, user, pwd, sender = _smtp_settings()
    if host and port and user and pwd and sender:
        return True
    return os.environ.get("PAYOUT_DEV_PRINT_EMAIL", "0").lower() in ("1", "true", "yes")


def send_email(to: str, subject: str, body: str) -> bool:
    """Send an email. Returns True if delivered (or printed in explicit dev
    mode), False if it could not be sent.

    Never raises on SMTP failure — logs the error and returns False so the
    auth flow can decide how to surface it to the user."""
    host, port, user, pwd, sender = _smtp_settings()

    if not (host and port and user and pwd and sender):
        if os.environ.get("PAYOUT_DEV_PRINT_EMAIL", "0").lower() in ("1", "true", "yes"):
            print("\n──── EMAIL (PAYOUT_DEV_PRINT_EMAIL — local dev only) ────")
            print(f"To:      {to}")
            print(f"Subject: {subject}")
            print(body)
            print("──────────────────────────────────────────────────────────\n")
            return True
        logger.warning("Email to %s not sent: SMTP is not configured", to)
        return False

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, int(port), timeout=10) as smtp:
            smtp.starttls(context=ctx)
            smtp.login(user, pwd)
            smtp.send_message(msg)
        return True
    except Exception as e:
        logger.exception("Failed to send email to %s: %s", to, e)
        return False
