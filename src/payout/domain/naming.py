"""What to call a user on screen.

An email address is a credential. Printed as a name it reads like one —
``YUVRAJ.GANGULY.DS26`` across the top of every screen in the recruiter app —
and it also puts a login id in front of anyone standing behind the phone.

There are two places a real name can come from, and they exist for different
reasons, so the order matters:

* ``recruiter_profiles.full_name`` — what the person typed about themselves on
  their own profile page. It is theirs, so it wins.
* ``users.display_name`` — what an admin set when the account was made. A
  reasonable stand-in until the person fills their profile in.

Only if both are empty does the email's local part stand in, because an account
with no name at all still has to render as something.

Every surface that shows a person's name uses this, so the app header, the
recruiter board and the console cannot end up disagreeing about what one person
is called.
"""

from __future__ import annotations

__all__ = ["display_name_for", "name_from"]


def name_from(full_name: str | None, display_name: str | None, email: str) -> str:
    """The name, given the two candidate columns and the email to fall back on.

    Split out from [display_name_for] so a query that has already fetched the
    columns — the recruiter board joins them for every row — does not run a
    second lookup per person.
    """
    for value in (full_name, display_name):
        cleaned = (value or "").strip()
        if cleaned:
            return cleaned
    return email.split("@")[0]


def display_name_for(conn, email: str) -> str:
    """The name for one user, looked up. One indexed read on the primary key."""
    row = conn.execute(
        "SELECT u.display_name, p.full_name FROM users u "
        "LEFT JOIN recruiter_profiles p ON p.email = u.email WHERE u.email=?",
        (email,),
    ).fetchone()
    if not row:
        return email.split("@")[0]
    return name_from(row["full_name"], row["display_name"], email)
