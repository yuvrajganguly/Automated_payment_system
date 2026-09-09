"""The recruiter as a subject: their profile, their odometer, their numbers.

Three things live here, all keyed on ``users.email``:

* **Profile** — the recruiter's own name, bank details, Aadhaar and PAN, and a
  photo. Written by the recruiter from the app; read in full only by that
  recruiter and by an admin opening their profile. Everywhere else the
  sensitive fields come back masked (see ``_mask``), so a list of thirty
  recruiters never carries thirty account numbers.
* **Shifts** — the vehicle odometer at the start and end of a day, with a photo
  of the dash each time. ``end_km - start_km`` is the day's distance; the
  month's sum is what the fuel compensation is paid on.
* **Analytics** — how many riders someone onboarded per day, week or month, how
  many of those are still working, which EVs they deployed, and how far they
  rode doing it.

None of this is money in the ledger sense — no route here writes a transaction —
but the odometer totals feed a payment made outside the system, so the readings
are treated as evidence: the photo keys and the timestamps are kept, and a
correction overwrites the row rather than appending a second one for the day.
"""

from __future__ import annotations

import contextlib
import re
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from payout.api.auth import get_current_user, require_admin
from payout.api.ratelimit import rate_limit
from payout.api.routes.users import visible_role
from payout.db import get_connection
from payout.documents import ALLOWED_CONTENT_TYPES, get_storage, make_staff_key
from payout.domain.activity import record_activity
from payout.domain.identity import normalize_aadhaar, normalize_pan
from payout.domain.naming import name_from
from payout.domain.worked import ACTIVE_WITHIN_DAYS, active_person_sql

router = APIRouter()

# Fields never returned in full outside the owner's own profile and an admin's
# view of it. A masked value keeps the last four characters so the office can
# match it against a passbook without the number itself travelling.
SENSITIVE_FIELDS = ("account_no", "aadhaar_no", "pan_no")

MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_KINDS = ("profile", "shift_start", "shift_end")

# An odometer that reads more than this in one day is a typo, not a commute.
MAX_DAILY_KM = 600
MAX_ODOMETER_KM = 2_000_000


def _mask(value: str | None) -> str | None:
    """``4521889012`` -> ``••••••9012``. None stays None; a short value is
    hidden entirely rather than leaked by being too short to mask."""
    if not value:
        return None
    tail = value[-4:] if len(value) > 4 else ""
    return "•" * max(len(value) - len(tail), 4) + tail


def _profile_row(conn, email: str) -> dict:
    row = conn.execute(
        # u.email, not p.email: the profile row is LEFT-joined and does not
        # exist until the recruiter first saves something, and a response whose
        # own identity field is null is worse than useless to the caller.
        "SELECT u.email AS email, p.full_name, p.phone, p.address, p.account_name, p.account_no, "
        "       p.ifsc, p.bank_name, p.aadhaar_no, p.pan_no, p.photo_key, p.updated_at, "
        "       u.role, u.zone, u.is_active, u.display_name, u.phone AS login_phone "
        "FROM users u LEFT JOIN recruiter_profiles p ON p.email = u.email "
        "WHERE u.email = ?",
        (email,),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "No such user")
    return dict(row)


def _profile_out(row: dict, *, full: bool, viewer: dict) -> dict:
    out = {
        "email": row["email"],
        "full_name": row.get("full_name"),
        "display_name": row.get("display_name"),
        "phone": row.get("phone") or row.get("login_phone"),
        "address": row.get("address") if full else None,
        "account_name": row.get("account_name"),
        "ifsc": row.get("ifsc"),
        "bank_name": row.get("bank_name"),
        # Through visible_role: the creator tier is invisible below itself,
        # and this route would otherwise hand it over where /api/users masks it.
        "role": visible_role(row.get("role") or "user", viewer),
        "zone": row.get("zone"),
        "is_active": bool(row.get("is_active", 1)),
        "has_photo": bool(row.get("photo_key")),
        "updated_at": row.get("updated_at"),
        "masked": not full,
    }
    for field in SENSITIVE_FIELDS:
        out[field] = row.get(field) if full else _mask(row.get(field))
    return out


def _may_read_in_full(user: dict, email: str) -> bool:
    """The recruiter themselves, or an admin. Nobody else sees the numbers —
    a recruiter cannot read a colleague's bank details."""
    return (user["email"] or "").lower() == email or user["role"] in ("admin", "creator")


def _resolve(user: dict, email: str | None) -> str:
    """Whose record is being asked for.

    ``me`` is an alias for the caller, so the app can use one URL shape for
    both "my numbers" and an admin looking at somebody. Anyone may address
    themselves; only an admin may name someone else.
    """
    me = (user["email"] or "").lower()
    if not email or email.lower() in ("me", me):
        return me
    if user["role"] not in ("admin", "creator"):
        raise HTTPException(403, "Only admins can look at another recruiter's record")
    return email.lower()


# ───────────────────────────── profile ──────────────────────────────────────


class ProfileIn(BaseModel):
    full_name: str | None = Field(None, max_length=120)
    phone: str | None = Field(None, max_length=20)
    address: str | None = Field(None, max_length=400)
    account_name: str | None = Field(None, max_length=120)
    account_no: str | None = Field(None, max_length=34)
    ifsc: str | None = Field(None, max_length=15)
    bank_name: str | None = Field(None, max_length=120)
    aadhaar_no: str | None = Field(None, max_length=20)
    pan_no: str | None = Field(None, max_length=12)


@router.get("/me/profile")
def my_profile(user: dict = Depends(get_current_user)) -> dict:
    """My own profile, in full. This is the only route a recruiter can use to
    read identity numbers, and it only ever returns their own."""
    with get_connection() as conn:
        return _profile_out(
            _profile_row(conn, (user["email"] or "").lower()), full=True, viewer=user
        )


@router.patch("/me/profile")
def update_my_profile(body: ProfileIn, user: dict = Depends(get_current_user)) -> dict:
    """Save my own details. Every field is optional and only the ones sent are
    written, so the app can save one section at a time on a bad connection.
    An empty string clears a field; omitting it leaves it alone."""
    email = (user["email"] or "").lower()
    sent = body.model_dump(exclude_unset=True)

    if "aadhaar_no" in sent and sent["aadhaar_no"]:
        try:
            sent["aadhaar_no"] = normalize_aadhaar(sent["aadhaar_no"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if "pan_no" in sent and sent["pan_no"]:
        try:
            sent["pan_no"] = normalize_pan(sent["pan_no"])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if "ifsc" in sent and sent["ifsc"]:
        ifsc = sent["ifsc"].strip().upper()
        if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", ifsc):
            raise HTTPException(400, "IFSC looks wrong — it is 4 letters, a 0, then 6 characters")
        sent["ifsc"] = ifsc
    if "account_no" in sent and sent["account_no"]:
        acct = re.sub(r"[\s-]", "", sent["account_no"])
        if not acct.isdigit() or not (6 <= len(acct) <= 20):
            raise HTTPException(400, "Account number should be 6 to 20 digits")
        sent["account_no"] = acct

    sent = {k: (v.strip() or None if isinstance(v, str) else v) for k, v in sent.items()}

    with get_connection() as conn:
        conn.execute("INSERT OR IGNORE INTO recruiter_profiles (email) VALUES (?)", (email,))
        if sent:
            cols = ", ".join(f"{k}=?" for k in sent)
            conn.execute(
                f"UPDATE recruiter_profiles SET {cols}, updated_at=datetime('now') "  # noqa: S608
                "WHERE email=?",
                (*sent.values(), email),
            )
        record_activity(
            conn,
            user,
            "profile.update",
            entity_type="recruiter",
            entity_id=email,
            label=email,
            # The fields that changed, never their values — this feed is read
            # by every admin and an Aadhaar number has no business in it.
            details={"fields": sorted(sent)},
        )
        conn.commit()
        return _profile_out(_profile_row(conn, email), full=True, viewer=user)


@router.get("/{email}/profile")
def recruiter_profile(email: str, user: dict = Depends(get_current_user)) -> dict:
    """One recruiter's profile. Full for an admin or the recruiter themselves,
    masked for anyone else who can see the console at all."""
    email = _resolve(user, email)
    with get_connection() as conn:
        return _profile_out(
            _profile_row(conn, email), full=_may_read_in_full(user, email), viewer=user
        )


# ───────────────────────────── photos ───────────────────────────────────────


def _read_photo(file: UploadFile) -> tuple[bytes, str]:
    ctype = (file.content_type or "").split(";")[0].strip().lower()
    if ctype not in ALLOWED_CONTENT_TYPES or ctype == "application/pdf":
        raise HTTPException(415, "Send a JPEG, PNG or WebP image")
    data = file.file.read(MAX_PHOTO_BYTES + 1)
    if not data:
        raise HTTPException(400, "The file was empty")
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "That image is too large — the app should shrink it first")
    return data, ctype


@router.post("/me/photo")
def upload_my_photo(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    _: None = Depends(rate_limit("staff-photo", 40, 3600)),
) -> dict:
    """My profile picture. Replaces whatever was there; the old object is
    deleted so the store does not accumulate every version of a face."""
    email = (user["email"] or "").lower()
    data, ctype = _read_photo(file)
    key = make_staff_key(email, "profile", ctype)
    get_storage().put(key, data, ctype)
    with get_connection() as conn:
        old = conn.execute(
            "SELECT photo_key FROM recruiter_profiles WHERE email=?", (email,)
        ).fetchone()
        conn.execute("INSERT OR IGNORE INTO recruiter_profiles (email) VALUES (?)", (email,))
        conn.execute(
            "UPDATE recruiter_profiles SET photo_key=?, updated_at=datetime('now') WHERE email=?",
            (key, email),
        )
        conn.commit()
    if old and old["photo_key"] and old["photo_key"] != key:
        # A stale object left behind is not worth failing an upload over.
        with contextlib.suppress(Exception):
            get_storage().delete(old["photo_key"])
    return {"ok": True}


@router.get("/{email}/photo")
def recruiter_photo(email: str, user: dict = Depends(get_current_user)) -> Response:
    """A recruiter's picture. Visible to any signed-in member of staff — it is
    a face on a directory, not an identity document."""
    email = (user["email"] or "").lower() if email.lower() == "me" else email.lower()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT photo_key FROM recruiter_profiles WHERE email=?", (email,)
        ).fetchone()
    if not row or not row["photo_key"]:
        raise HTTPException(404, "No photo")
    try:
        data = get_storage().get(row["photo_key"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, "No photo") from exc
    ext = row["photo_key"].rsplit(".", 1)[-1]
    ctype = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    return Response(
        content=data, media_type=ctype, headers={"Cache-Control": "private, max-age=300"}
    )


# ───────────────────────────── shifts ───────────────────────────────────────


class ShiftIn(BaseModel):
    kind: str = Field(..., pattern="^(start|end)$")
    km: int = Field(..., ge=0, le=MAX_ODOMETER_KM)
    day: str | None = Field(None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    note: str | None = Field(None, max_length=200)


def _open_day_before(conn, email: str, day: str):
    """The oldest day before ``day`` that was opened and never closed.

    A day left open contributes nothing to the month's total and there is no
    honest way to reconstruct it afterwards — nobody remembers Tuesday's
    closing reading in October. So the next opening is refused until it is
    dealt with. It is the only block in this module, and it exists because the
    alternative is a fuel claim that is quietly short and a recruiter who finds
    out at the end of the month.
    """
    return conn.execute(
        "SELECT * FROM recruiter_shifts WHERE email=? AND day<? "
        "AND start_km IS NOT NULL AND end_km IS NULL ORDER BY day LIMIT 1",
        (email, day),
    ).fetchone()


def _shift_out(row) -> dict:
    start, end = row["start_km"], row["end_km"]
    # max(0, …): a distance can never be negative, and a row that somehow holds
    # end below start must not subtract from a fuel claim.
    distance = max(0, int(end) - int(start)) if start is not None and end is not None else None
    return {
        "id": int(row["id"]),
        "email": row["email"],
        "day": row["day"],
        "start_km": None if start is None else int(start),
        "end_km": None if end is None else int(end),
        "distance_km": distance,
        "start_at": row["start_at"],
        "end_at": row["end_at"],
        "has_start_photo": bool(row["start_photo_key"]),
        "has_end_photo": bool(row["end_photo_key"]),
        "note": row["note"],
        "complete": distance is not None,
    }


@router.post("/me/shift")
def save_shift(body: ShiftIn, user: dict = Depends(get_current_user)) -> dict:
    """Record the odometer at the start or end of my day.

    Saved before the photo, deliberately: the number is the claim and the photo
    is the evidence, and a failed upload on a hub's signal must not lose the
    number. Re-sending a reading for the same day corrects it.

    Two guards, one hard and one soft. An end below the start is refused —
    that is arithmetic, not judgement. A start below yesterday's end only
    *warns*: vehicles get swapped, serviced and replaced, and blocking the
    shift because the odometer went backwards would leave a recruiter unable
    to record their day.
    """
    email = (user["email"] or "").lower()
    day = body.day or date.today().isoformat()
    if day > date.today().isoformat():
        raise HTTPException(400, "That day has not happened yet")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    warnings: list[str] = []

    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO recruiter_shifts (email, day) VALUES (?, ?)", (email, day)
        )
        row = conn.execute(
            "SELECT * FROM recruiter_shifts WHERE email=? AND day=?", (email, day)
        ).fetchone()

        if body.kind == "end":
            if row["start_km"] is None:
                raise HTTPException(400, "Record the starting reading first")
            if body.km < int(row["start_km"]):
                raise HTTPException(
                    400,
                    f"The closing reading ({body.km:,} km) is below the opening one "
                    f"({int(row['start_km']):,} km)",
                )
            if body.km - int(row["start_km"]) > MAX_DAILY_KM:
                warnings.append(
                    f"That is {body.km - int(row['start_km']):,} km in one day — check the reading"
                )
            # The comparison is repeated inside the UPDATE, not just checked
            # above. Between the SELECT and here another save can land — two
            # taps on a flaky hub connection is all it takes — and a row with
            # end below start would flow straight into the fuel claim as a
            # negative distance. Re-stating the condition in the WHERE makes
            # the database the arbiter.
            cur = conn.execute(
                "UPDATE recruiter_shifts SET end_km=?, end_at=?, note=COALESCE(?, note) "
                "WHERE email=? AND day=? AND start_km IS NOT NULL AND start_km <= ?",
                (body.km, now, body.note, email, day, body.km),
            )
            if not cur.rowcount:
                raise HTTPException(400, "That reading no longer fits the day — reload and retry")
        else:
            stale = _open_day_before(conn, email, day)
            if stale is not None:
                raise HTTPException(
                    400,
                    f"{stale['day']} was opened at {int(stale['start_km']):,} km and never "
                    "closed. Close it first — the reading you parked on, or mark it a day "
                    "you did not ride.",
                )
            if row["end_km"] is not None and body.km > int(row["end_km"]):
                raise HTTPException(
                    400,
                    f"The opening reading ({body.km:,} km) is above the closing one already "
                    f"recorded ({int(row['end_km']):,} km)",
                )
            prev = conn.execute(
                "SELECT end_km, day FROM recruiter_shifts "
                "WHERE email=? AND day<? AND end_km IS NOT NULL ORDER BY day DESC LIMIT 1",
                (email, day),
            ).fetchone()
            if prev and body.km < int(prev["end_km"]):
                warnings.append(
                    f"Lower than the closing reading on {prev['day']} "
                    f"({int(prev['end_km']):,} km) — a different vehicle?"
                )
            cur = conn.execute(
                "UPDATE recruiter_shifts SET start_km=?, start_at=?, note=COALESCE(?, note) "
                "WHERE email=? AND day=? AND (end_km IS NULL OR end_km >= ?)",
                (body.km, now, body.note, email, day, body.km),
            )
            if not cur.rowcount:
                raise HTTPException(400, "That reading no longer fits the day — reload and retry")

        record_activity(
            conn,
            user,
            f"shift.{body.kind}",
            entity_type="shift",
            entity_id=f"{email}@{day}",
            label=day,
            details={"km": body.km},
        )
        conn.commit()
        saved = conn.execute(
            "SELECT * FROM recruiter_shifts WHERE email=? AND day=?", (email, day)
        ).fetchone()
        return {**_shift_out(saved), "warnings": warnings}


@router.post("/me/shift/photo")
def upload_shift_photo(
    kind: str = Query(..., pattern="^(start|end)$"),
    day: str | None = Query(None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    _: None = Depends(rate_limit("staff-photo", 40, 3600)),
) -> dict:
    """The photo of the dash for one half of a day. The reading must already
    be saved — the photo hangs off it, not the other way round."""
    email = (user["email"] or "").lower()
    day = day or date.today().isoformat()
    data, ctype = _read_photo(file)
    col = "start_photo_key" if kind == "start" else "end_photo_key"
    key = make_staff_key(email, f"shift_{kind}", ctype)
    get_storage().put(key, data, ctype)
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM recruiter_shifts WHERE email=? AND day=?", (email, day)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Save the reading for that day first")
        old = row[col]
        conn.execute(
            f"UPDATE recruiter_shifts SET {col}=? WHERE email=? AND day=?",  # noqa: S608
            (key, email, day),
        )
        conn.commit()
    if old and old != key:
        with contextlib.suppress(Exception):
            get_storage().delete(old)
    return {"ok": True}


@router.get("/{email}/shift/photo")
def shift_photo(
    email: str,
    kind: str = Query(..., pattern="^(start|end)$"),
    day: str = Query(..., pattern=r"^\d{4}-\d{2}-\d{2}$"),
    user: dict = Depends(get_current_user),
) -> Response:
    """The dash photo behind a day's reading — the evidence for the claim.
    The recruiter who took it, or an admin checking it."""
    email = _resolve(user, email)
    col = "start_photo_key" if kind == "start" else "end_photo_key"
    with get_connection() as conn:
        row = conn.execute(
            f"SELECT {col} AS k FROM recruiter_shifts WHERE email=? AND day=?",  # noqa: S608
            (email, day),
        ).fetchone()
    if not row or not row["k"]:
        raise HTTPException(404, "No photo")
    try:
        data = get_storage().get(row["k"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(404, "No photo") from exc
    ext = row["k"].rsplit(".", 1)[-1]
    ctype = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}.get(ext, "image/jpeg")
    return Response(
        content=data, media_type=ctype, headers={"Cache-Control": "private, max-age=300"}
    )


@router.get("/me/shift/today")
def my_shift_today(user: dict = Depends(get_current_user)) -> dict:
    """Today's row, plus the earlier day that is blocking it, if there is one.

    ``open_before`` is the whole point of this shape: the app cannot ask a
    recruiter to close Tuesday unless it knows Tuesday is open, and the day
    list on Profile is not where somebody standing outside a store at 7 a.m.
    is looking.
    """
    email = (user["email"] or "").lower()
    day = date.today().isoformat()
    with get_connection() as conn:
        stale = _open_day_before(conn, email, day)
        blocking = _shift_out(stale) if stale is not None else None
        row = conn.execute(
            "SELECT * FROM recruiter_shifts WHERE email=? AND day=?", (email, day)
        ).fetchone()
        if row is None:
            return {
                "open_before": blocking,
                "id": None,
                "email": email,
                "day": day,
                "start_km": None,
                "end_km": None,
                "distance_km": None,
                "start_at": None,
                "end_at": None,
                "has_start_photo": False,
                "has_end_photo": False,
                "note": None,
                "complete": False,
            }
        return {**_shift_out(row), "open_before": blocking}


@router.get("/{email}/shifts")
def shifts(
    email: str,
    days: int = Query(30, ge=1, le=400),
    user: dict = Depends(get_current_user),
) -> dict:
    """Day-by-day readings and distance. A recruiter sees their own; an admin
    may name anyone. Days with no row are simply absent — a recruiter who did
    not ride did not record a reading, and inventing a zero would flatter the
    average."""
    email = _resolve(user, email)
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    with get_connection() as conn:
        rows = [
            _shift_out(r)
            for r in conn.execute(
                "SELECT * FROM recruiter_shifts WHERE email=? AND day>=? ORDER BY day DESC",
                (email, since),
            )
        ]
    total = sum(r["distance_km"] or 0 for r in rows)
    complete = [r for r in rows if r["complete"]]
    return {
        "email": email,
        "since": since,
        "days": rows,
        "total_km": total,
        "days_recorded": len(complete),
        "average_km": round(total / len(complete), 1) if complete else None,
        "incomplete": [r["day"] for r in rows if not r["complete"]],
    }


@router.get("/{email}/shifts/monthly")
def shifts_monthly(
    email: str,
    months: int = Query(12, ge=1, le=36),
    user: dict = Depends(get_current_user),
) -> dict:
    """Month-by-month distance — the number the fuel claim is paid on.

    Only days with both readings count. An open day contributes nothing and is
    reported separately, so a month total is never quietly short by a day
    somebody forgot to close.
    """
    email = _resolve(user, email)
    with get_connection() as conn:
        rows = [
            {
                "month": r["m"],
                "km": int(r["km"] or 0),
                "days_recorded": int(r["n"] or 0),
                "days_open": int(r["open_days"] or 0),
            }
            for r in conn.execute(
                "SELECT substr(day,1,7) AS m, "
                "  SUM(CASE WHEN end_km IS NOT NULL AND start_km IS NOT NULL "
                "                AND end_km >= start_km "
                "           THEN end_km - start_km ELSE 0 END) AS km, "
                "  SUM(CASE WHEN end_km IS NOT NULL AND start_km IS NOT NULL "
                "           THEN 1 ELSE 0 END) AS n, "
                "  SUM(CASE WHEN end_km IS NULL OR start_km IS NULL "
                "           THEN 1 ELSE 0 END) AS open_days "
                "FROM recruiter_shifts WHERE email=? GROUP BY substr(day,1,7) "
                "ORDER BY m DESC LIMIT ?",
                (email, months),
            )
        ]
    return {"email": email, "months": rows}


# ─────────────────────────── analytics ──────────────────────────────────────


def _bucket_of(day: str | None, grain: str) -> str | None:
    """Which bucket a ``YYYY-MM-DD`` string falls in.

    Bucketing happens in Python, not SQL. The obvious SQL forms need
    ``strftime`` or ``date_trunc``, neither of which the dialect-translation
    layer rewrites, so a week bucket written in SQL would work on SQLite and
    quietly fail on PostgreSQL — the exact class of bug the dual-database test
    run exists to catch. One recruiter's onboardings are a few hundred rows;
    grouping them here costs nothing.
    """
    if not day:
        return None
    day = day[:10]
    if grain == "month":
        return day[:7]
    if grain == "day":
        return day
    try:
        d = date.fromisoformat(day)
    except ValueError:
        return None
    return (d - timedelta(days=d.weekday())).isoformat()  # the Monday of that week


@router.get("")
def recruiter_board(
    days: int = Query(30, ge=1, le=365, description="window for the 'recent' column"),
    user: dict = Depends(require_admin),
) -> dict:
    """Every recruiter, one row each, ordered best first.

    'Best' is onboardings in the window; the table on the web console re-sorts
    client-side, so this only fixes a sensible default. ``still_working`` is
    the 12-day rule from ``domain/worked.py`` applied to the riders this person
    onboarded — the retention number, and the one worth arguing about.
    """
    since = (date.today() - timedelta(days=days - 1)).isoformat()
    month_start = date.today().replace(day=1).isoformat()
    active = active_person_sql("rm.person_id")
    with get_connection() as conn:
        rows = []
        for r in conn.execute(
            "SELECT u.email, u.display_name, u.zone, u.is_active, p.full_name, "
            "       p.photo_key IS NOT NULL AS has_photo "
            "FROM users u LEFT JOIN recruiter_profiles p ON p.email = u.email "
            # Recruiters only. Admins and the creator were included because
            # they *can* onboard a rider and hand over an EV, so their rows
            # would not be empty — but this board exists to compare field
            # staff against each other, and an office account sitting in it
            # with a handful of corrections distorts the ordering and the
            # retention column it is read for. An admin who has genuinely
            # onboarded riders is still reachable at /recruiters/<email>.
            "WHERE u.role = 'recruiter' ORDER BY u.email"
        ):
            email = r["email"]
            counts = conn.execute(
                "SELECT COUNT(*) AS all_time, "
                "  SUM(CASE WHEN substr(rm.created_at,1,10) >= ? THEN 1 ELSE 0 END) AS recent, "
                "  SUM(CASE WHEN substr(rm.created_at,1,10) >= ? THEN 1 ELSE 0 END) AS month, "
                f"  SUM(CASE WHEN {active} THEN 1 ELSE 0 END) AS still_working "
                "FROM rider_master rm WHERE rm.recruited_by=?",
                (since, month_start, email),
            ).fetchone()
            evs = conn.execute(
                "SELECT COUNT(*) AS n, "
                "  SUM(CASE WHEN substr(handover_date,1,10) >= ? THEN 1 ELSE 0 END) AS recent "
                "FROM ev_assignments WHERE assigned_by=?",
                (since, email),
            ).fetchone()
            km = conn.execute(
                "SELECT COALESCE(SUM(end_km - start_km), 0) AS km FROM recruiter_shifts "
                "WHERE email=? AND day>=? AND start_km IS NOT NULL AND end_km IS NOT NULL",
                (email, month_start),
            ).fetchone()
            if not (counts["all_time"] or evs["n"] or km["km"]) and r["is_active"] != 1:
                continue  # a deactivated account that never did anything
            rows.append(
                {
                    "email": email,
                    "name": name_from(r["full_name"], r["display_name"], email),
                    "zone": r["zone"],
                    "is_active": bool(r["is_active"]),
                    "has_photo": bool(r["has_photo"]),
                    "onboarded_all_time": int(counts["all_time"] or 0),
                    "onboarded_recent": int(counts["recent"] or 0),
                    "onboarded_month": int(counts["month"] or 0),
                    "still_working": int(counts["still_working"] or 0),
                    "evs_deployed": int(evs["n"] or 0),
                    "evs_deployed_recent": int(evs["recent"] or 0),
                    "km_this_month": int(km["km"] or 0),
                }
            )
    for row in rows:
        base = row["onboarded_all_time"]
        row["retention_pct"] = round(100 * row["still_working"] / base, 1) if base else None
    rows.sort(key=lambda r: (-r["onboarded_recent"], -r["onboarded_all_time"], r["email"]))
    return {
        "since": since,
        "window_days": days,
        "active_within_days": ACTIVE_WITHIN_DAYS,
        "recruiters": rows,
    }


@router.get("/{email}/series")
def recruiter_series(
    email: str,
    grain: str = Query("week", pattern="^(day|week|month)$"),
    buckets: int = Query(12, ge=1, le=104),
    user: dict = Depends(get_current_user),
) -> dict:
    """Onboardings per day, week or month for one recruiter, with how many of
    each cohort are still working and how far they rode in that bucket.

    The retention figure is a *cohort* number: of the riders signed up in this
    bucket, how many are working now. It is not "how many were working then" —
    the ledger cannot answer that retrospectively without replaying every
    cycle, and pretending otherwise would put a wrong number on a chart.
    """
    email = _resolve(user, email)
    active = active_person_sql("rm.person_id")
    onboard: dict[str, dict[str, int]] = {}
    km: dict[str, int] = {}
    evs: dict[str, int] = {}

    with get_connection() as conn:
        for r in conn.execute(
            "SELECT substr(rm.created_at,1,10) AS d, "
            f"       ({active}) AS w "  # noqa: S608 - active is built from literals
            "FROM rider_master rm "
            "WHERE rm.recruited_by=? AND rm.created_at IS NOT NULL",
            (email,),
        ):
            b = _bucket_of(r["d"], grain)
            if b is None:
                continue
            cell = onboard.setdefault(b, {"onboarded": 0, "still_working": 0})
            cell["onboarded"] += 1
            cell["still_working"] += 1 if r["w"] else 0
        for r in conn.execute(
            "SELECT day, end_km - start_km AS km FROM recruiter_shifts "
            "WHERE email=? AND start_km IS NOT NULL AND end_km IS NOT NULL",
            (email,),
        ):
            b = _bucket_of(r["day"], grain)
            if b is not None:
                km[b] = km.get(b, 0) + int(r["km"] or 0)
        for r in conn.execute(
            "SELECT substr(handover_date,1,10) AS d FROM ev_assignments "
            "WHERE assigned_by=? AND handover_date IS NOT NULL",
            (email,),
        ):
            b = _bucket_of(r["d"], grain)
            if b is not None:
                evs[b] = evs.get(b, 0) + 1

    keys = sorted(set(onboard) | set(km) | set(evs))[-buckets:]
    series = [
        {
            "bucket": k,
            "onboarded": onboard.get(k, {}).get("onboarded", 0),
            "still_working": onboard.get(k, {}).get("still_working", 0),
            "evs_deployed": evs.get(k, 0),
            "km": km.get(k, 0),
        }
        for k in keys
    ]
    return {
        "email": email,
        "grain": grain,
        "active_within_days": ACTIVE_WITHIN_DAYS,
        "series": series,
        "totals": {
            "onboarded": sum(s["onboarded"] for s in series),
            "still_working": sum(s["still_working"] for s in series),
            "evs_deployed": sum(s["evs_deployed"] for s in series),
            "km": sum(s["km"] for s in series),
        },
    }


@router.get("/{email}/riders")
def recruiter_riders(
    email: str,
    status: str = Query("all", pattern="^(all|working|idle|holding)$"),
    limit: int = Query(200, ge=1, le=2000),
    user: dict = Depends(get_current_user),
) -> list[dict]:
    """The riders this recruiter onboarded, each flagged working or idle by the
    12-day rule, newest first.

    ``holding`` is the odd one out: it lists the people who have an EV out
    right now, and it returns **one row per person**, not one per rider id.
    That is deliberate. The count it sits behind (``counts.ev_holders``) is a
    ``COUNT(DISTINCT person_id)`` — one vehicle, one holder — so a person
    carrying two company rider ids would otherwise appear twice under a tile
    that said 1. A tile that disagrees with the list behind it is worse than
    no list at all.
    """
    email = _resolve(user, email)
    active = active_person_sql("rm.person_id")
    holds = (
        "EXISTS (SELECT 1 FROM ev_assignments _ha WHERE _ha.person_id = rm.person_id "
        "AND _ha.returned_date IS NULL)"
    )
    # One row per person for `holding`: keep the first of this recruiter's
    # rows for that person. The comparison is on the WHOLE key, (rider_id,
    # company) — a rider id is not unique on its own. Companies that share
    # ids (companies.rider_ids_shared_with, and _auto_link_rider) put the
    # same id under two companies for one person, and a MIN(rider_id) test
    # would match both of those rows and hand back the duplicate this is
    # here to prevent.
    one_per_person = (
        " AND NOT EXISTS (SELECT 1 FROM rider_master _rm2 "
        "WHERE _rm2.person_id = rm.person_id AND _rm2.recruited_by = rm.recruited_by "
        "AND (_rm2.rider_id, _rm2.company) < (rm.rider_id, rm.company))"
    )
    where = {
        "all": "",
        "working": f" AND {active}",
        "idle": f" AND NOT {active}",
        "holding": f" AND {holds}{one_per_person}",
    }[status]
    from payout.domain.worked import last_worked_sql

    with get_connection() as conn:
        return [
            {
                "rider_id": r["rider_id"],
                "company_name": r["company"],
                "name": r["name"],
                "person_id": int(r["person_id"]),
                "hub": r["hub"],
                "created_at": r["created_at"],
                "on_roster": bool(r["is_active"]),
                "working": bool(r["working"]),
                "last_worked_on": r["last_worked_on"],
                "ev_id": r["ev_id"],
            }
            for r in conn.execute(
                "SELECT rm.rider_id, rm.company, rm.name, rm.person_id, rm.hub, "
                "       rm.created_at, rm.is_active, "
                f"      ({active}) AS working, "  # noqa: S608 - both are literals above
                f"      {last_worked_sql('rm.person_id')} AS last_worked_on, "
                # The EV they are holding right now, if any — shown as a badge
                # in every list, not only the holding one.
                "       (SELECT _ea.ev_id FROM ev_assignments _ea "
                "        WHERE _ea.person_id = rm.person_id AND _ea.returned_date IS NULL "
                "        ORDER BY _ea.handover_date DESC, _ea.assignment_id DESC "
                "        LIMIT 1) AS ev_id "
                f"FROM rider_master rm WHERE rm.recruited_by=?{where} "
                "ORDER BY rm.created_at DESC, rm.rider_id DESC LIMIT ?",
                (email, limit),
            )
        ]


@router.get("/{email}/evs")
def recruiter_evs(
    email: str,
    limit: int = Query(200, ge=1, le=2000),
    user: dict = Depends(get_current_user),
) -> list[dict]:
    """Every EV this recruiter handed over, with who has it now and whether it
    has come back. Attribution comes from ``ev_assignments.assigned_by``,
    backfilled from the activity feed by migration 0026 — assignments made
    before that column existed and never logged simply have no name."""
    email = _resolve(user, email)
    with get_connection() as conn:
        return [
            {
                "assignment_id": int(r["assignment_id"]),
                "ev_id": r["ev_id"],
                "person_id": int(r["person_id"]),
                "rider_name": r["display_name"],
                "handover_date": r["handover_date"],
                "returned_date": r["returned_date"],
                "returned_by": r["returned_by"],
                "still_held": r["returned_date"] is None,
                "model": r["model"],
                "provider": r["provider"],
            }
            for r in conn.execute(
                "SELECT ea.assignment_id, ea.ev_id, ea.person_id, ea.handover_date, "
                "       ea.returned_date, ea.returned_by, pr.display_name, "
                "       em.model_name AS model, em.provider "
                "FROM ev_assignments ea "
                "JOIN person_registry pr ON pr.person_id = ea.person_id "
                "LEFT JOIN ev_units eu ON eu.ev_id = ea.ev_id "
                "LEFT JOIN ev_models em ON em.model_id = eu.model_id "
                "WHERE ea.assigned_by=? "
                "ORDER BY ea.handover_date DESC, ea.assignment_id DESC LIMIT ?",
                (email, limit),
            )
        ]
