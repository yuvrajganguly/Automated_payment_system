#!/usr/bin/env python
"""Raft reconciliation fixes for the LIVE database — 11 Sep 2026.

What it does (in ONE transaction, rolled back unless --apply is given):

  1. EV ids typed with a trailing space ("CBICEVD0130 ") are trimmed.
  2. Gopal Shaw's EV  CBICEVD0219 -> CBICEVD0265   (Raft Chinar Park report)
     Lokenath Sarkar  CBICEVD0221 -> CBICEVD0254   (Raft Chinar Park report)
     A rename copies the unit under the new id, re-points every child row
     (assignments, day-ledger, maintenance, close-outs, provider bill lines)
     and drops the old id — the FKs are not ON UPDATE CASCADE.
  3. The 7 post-7-Sep Raft deployments missing from the DB are added:
     placeholder rider id (QSPEND….) under Jiffy (the company formerly called
     Spencer's), phone from the Raft report, unit model Raft/Blue, open
     assignment from the Raft deploy date. If a rider with that phone already
     exists, the EV is attached to that person instead of creating a duplicate.
  4. EVs in the DB that Raft no longer lists are RETURNED (not deleted):
     CBICEVD0005 Milon Sardar, CBICEVD0055 Rahul Das (split), EV1734 Mala Dey,
     EV1809 Taraknath Biswas — exactly what the web's Return button does
     (rent stops, backdated-rent heal, security-deposit close-out prompt).
     Sibom Dutta's AV135 is kept.
  5. EV1746 (returned 27 Jun) becomes SPARE — Raft still lists it as deployed.
  6. Banti Das / CBICED0135: only a side-by-side with Shyamsundar Das /
     CBICEVD0135 is printed (same person?). With --banti-dup the duplicate
     record CBICED0135 (created 11 Sep, never billed) is deleted; the person
     merge itself is done in the web (Riders -> Link riders).

Run inside the app container on the server (bash):

    cd /root/payout/deploy
    docker exec -i payout python - < ev_fix_2026_09_11.py                 # dry run
    docker exec -i payout python - --apply < ev_fix_2026_09_11.py         # commit
    docker exec -i payout python - --apply --banti-dup < ev_fix_2026_09_11.py

Options:
    --apply              commit (default is a dry run that rolls back)
    --as EMAIL           who the activity log should say did this
                         (default: script:ev-fix-2026-09-11)
    --return-date DATE   return date for step 4 (default: today, IST)
    --banti-dup          also delete the duplicate CBICED0135 record (step 6)
"""

from __future__ import annotations

import argparse
import inspect
import sys
import traceback
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

from payout.api.routes.riders import _insert_rider_into_db
from payout.db import get_connection
from payout.domain.return_heal import heal_backdated_return

# The deployed image may be a little older or newer than the code this script
# was written against (2026-09-11, migration 0032). Everything that appeared
# recently is imported softly and checked at run time, so the script degrades
# to plain SQL instead of crashing half-way (nothing is committed on a crash
# anyway, but a clear message beats a traceback).
try:
    from payout.domain.activity import record_activity as _record_activity
except ImportError:  # pragma: no cover - older image
    _record_activity = None
try:
    from payout.domain.closeout import mark_pending as _mark_pending
except ImportError:  # pragma: no cover
    _mark_pending = None
try:
    from payout.api.routes.evs import _open_assignment as _live_open_assignment
except ImportError:  # pragma: no cover
    _live_open_assignment = None

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).date().isoformat()
NOTES: list[str] = []  # compatibility notes printed at the end

# ── the facts ────────────────────────────────────────────────────────────────
RENAMES = [  # (old id as stored, new id, expected holder — first word of the name)
    ("CBICEVD0219", "CBICEVD0265", "gopal"),
    ("CBICEVD0221", "CBICEVD0254", "lokenath"),
]

NEW_DEPLOYMENTS = [  # Raft active-riders reports, deployments after 7 Sep not yet in the DB
    # ev_id,        name (as on the Raft report), contact,      deploy,       hub,          VIN
    ("CBICEVD0251", "RANAJIT GHOSH", "9330833299", "2026-09-08", "Ruby", "RCEV/K1/01515"),
    ("CBICEVD0252", "SUBROTO MONDAL", "8910492614", "2026-09-08", "Ruby", "RCEV/K1/01510"),
    ("CBICEVD0258", "SANJIB CHAKRABORTY", "8777251171", "2026-09-08", "Ruby", "RCEV/K1/01520"),
    ("CBICEVD0250", "SHIBAM PRAMANICK", "7003664227", "2026-09-08", "Chinar Park", "RCEV/K1/01514"),
    ("CBICEVD0117", "DEEPAK KUMAR RAY", "6290726239", "2026-09-09", "Chinar Park", "RCEV/K1/01315"),
    (
        "CBICEVD0284",
        "ADITYA ROYCHOWDHURY",
        "6290226192",
        "2026-09-10",
        "Chinar Park",
        "RCEV/K1/01513",
    ),
    ("CBICEVD0286", "SUMAN MONDAL", "8910797718", "2026-09-10", "Chinar Park", "RCEV/K1/01529"),
]

RETURNS = [  # (ev_id, expected holder token) — in the DB but on neither Raft report
    ("CBICEVD0005", "milon"),
    ("CBICEVD0055", "rahul das"),
    ("EV1734", "mala dey"),
    ("EV1809", "taraknath"),
]
KEEP = ["AV135"]  # Sibom Dutta — stays, on the owner's instruction

SPARE = "EV1746"  # Ayan Mandal on Raft's list, returned in the DB -> spare

BANTI_BAD_ID = "CBICED0135"  # malformed (missing the V)
BANTI_TWIN_ID = "CBICEVD0135"  # Shyamsundar Das's unit
BANTI_TWIN_PHONE = "6290430787"  # Raft's contact for Shyamsundar Das

EV_CHILD_TABLES = [
    "ev_assignments",
    "ev_daily_ledger",
    "ev_maintenance",
    "ev_closeouts",
    "ev_closeout_reports",
    "provider_bill_lines",
]


# ── helpers ──────────────────────────────────────────────────────────────────
def say(msg: str = "") -> None:
    print(msg, flush=True)


def note(msg: str) -> None:
    if msg not in NOTES:
        NOTES.append(msg)


def one(conn, sql, params=()):
    return conn.execute(sql, params).fetchone()


def all_(conn, sql, params=()):
    return conn.execute(sql, params).fetchall()


def is_postgres() -> bool:
    from payout.config import DB_URL

    return bool(DB_URL)


def table_exists(conn, name: str) -> bool:
    if is_postgres():
        row = one(
            conn,
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema=current_schema() AND table_name=?",
            (name,),
        )
    else:
        row = one(conn, "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,))
    return row is not None


def has_column(conn, table: str, column: str) -> bool:
    if is_postgres():
        row = one(
            conn,
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name=? AND column_name=?",
            (table, column),
        )
        return row is not None
    return column in {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


# ── version-tolerant wrappers around the app's own write paths ───────────────
def record_activity(conn, user, action, **kw) -> None:
    """Activity feed row, when the deployed code has the feed."""
    if _record_activity is None or not table_exists(conn, "activity_log"):
        note("activity feed not present on this build — actions were not logged there")
        return
    _record_activity(conn, user, action, **kw)


def mark_pending(conn, assignment_id: int) -> None:
    """Flag the closed assignment for the security-deposit close-out prompt."""
    if _mark_pending is not None and has_column(conn, "ev_assignments", "closeout_pending"):
        _mark_pending(conn, assignment_id)
    else:
        note(
            "close-out prompts not present on this build "
            "— settle the returned riders' deposits by hand"
        )


def open_assignment(conn, ev_id: str, pid: int, handover: date, by: str) -> str:
    """The app's own assign path (one open EV per person, unit -> in_use)."""
    if _live_open_assignment is not None:
        params = inspect.signature(_live_open_assignment).parameters
        if "by" in params:
            return _live_open_assignment(conn, ev_id, pid, handover, by)
        return _live_open_assignment(conn, ev_id, pid, handover)
    # very old build: replicate assign_ev by hand
    if one(
        conn, "SELECT 1 FROM ev_assignments WHERE person_id=? AND returned_date IS NULL", (pid,)
    ):
        raise HTTPException(409, "Person already has an open EV assignment")
    if one(conn, "SELECT 1 FROM ev_assignments WHERE ev_id=? AND returned_date IS NULL", (ev_id,)):
        raise HTTPException(409, "EV already assigned to someone else")
    hod = handover.isoformat()
    if has_column(conn, "ev_assignments", "assigned_by"):
        conn.execute(
            "INSERT INTO ev_assignments (person_id, ev_id, handover_date, assigned_by) "
            "VALUES (?,?,?,?)",
            (pid, ev_id, hod, by),
        )
    else:
        conn.execute(
            "INSERT INTO ev_assignments (person_id, ev_id, handover_date) VALUES (?,?,?)",
            (pid, ev_id, hod),
        )
    conn.execute("UPDATE ev_units SET status='in_use' WHERE ev_id=?", (ev_id,))
    return hod


def insert_rider(conn, *, company: str, name: str, mob_no: str):
    """Placeholder rider + new person, through the app's own insert path."""
    params = inspect.signature(_insert_rider_into_db).parameters
    kw = dict(
        rider_id=None,
        company=company,
        name=name,
        hub=None,
        vehicle="EV",
        account_no=None,
        ifsc=None,
    )
    if "mob_no" in params:
        kw["mob_no"] = mob_no
    created, rider_id, pid = _insert_rider_into_db(conn, **kw)
    if "mob_no" not in params and has_column(conn, "rider_master", "mob_no"):
        conn.execute(
            "UPDATE rider_master SET mob_no=? WHERE rider_id=? AND company=?",
            (mob_no, rider_id, company),
        )
    return created, rider_id, pid


def close_assignment(conn, assignment_id: int, ret_date: str, by: str) -> None:
    if has_column(conn, "ev_assignments", "returned_by"):
        conn.execute(
            "UPDATE ev_assignments SET returned_date=?, returned_by=? WHERE assignment_id=?",
            (ret_date, by, assignment_id),
        )
    else:
        conn.execute(
            "UPDATE ev_assignments SET returned_date=? WHERE assignment_id=?",
            (ret_date, assignment_id),
        )


def close_open_maintenance(conn, ev_id: str, today: str) -> None:
    """Same as routes.evs._close_open_maintenance — a returned/spared unit is not in maintenance."""
    if table_exists(conn, "ev_maintenance"):
        conn.execute(
            "UPDATE ev_maintenance SET to_date=? WHERE ev_id=? "
            "AND to_date IS NULL AND from_date <= ?",
            (today, ev_id, today),
        )


def holder(conn, ev_id: str):
    """(person_id, display_name, handover_date, assignment_id) of the open assignment, or None."""
    return one(
        conn,
        "SELECT a.assignment_id, a.person_id, pr.display_name, a.handover_date "
        "FROM ev_assignments a JOIN person_registry pr ON pr.person_id=a.person_id "
        "WHERE a.ev_id=? AND a.returned_date IS NULL",
        (ev_id,),
    )


def ev_row(conn, ev_id: str):
    return one(
        conn,
        "SELECT u.ev_id, u.status, u.notes, m.provider, m.model_name, u.model_id "
        "FROM ev_units u JOIN ev_models m ON m.model_id=u.model_id WHERE u.ev_id=?",
        (ev_id,),
    )


def describe_ev(conn, ev_id: str) -> str:
    u = ev_row(conn, ev_id)
    if not u:
        return f"{ev_id!r}: (no such unit)"
    h = holder(conn, ev_id)
    who = (
        f"{h['display_name']} (person {h['person_id']}) since {h['handover_date']}"
        if h
        else "nobody"
    )
    return f"{u['ev_id']!r:16} {u['provider']}/{u['model_name']:8} {u['status']:10} -> {who}"


def rename_ev(conn, user: dict, old: str, new: str) -> None:
    """Copy the unit under ``new``, re-point every child row, drop ``old``."""
    u = ev_row(conn, old)
    if not u:
        raise RuntimeError(f"rename: {old!r} does not exist")
    if ev_row(conn, new):
        raise RuntimeError(f"rename: target {new!r} already exists")
    conn.execute(
        "INSERT INTO ev_units (ev_id, model_id, status, notes) VALUES (?,?,?,?)",
        (new, u["model_id"], u["status"], u["notes"]),
    )
    moved = {}
    for t in EV_CHILD_TABLES:
        if not table_exists(conn, t):
            continue
        cur = conn.execute(f"UPDATE {t} SET ev_id=? WHERE ev_id=?", (new, old))
        moved[t] = cur.rowcount
    conn.execute("DELETE FROM ev_units WHERE ev_id=?", (old,))
    record_activity(
        conn,
        user,
        "ev.rename",
        entity_type="ev",
        entity_id=new,
        label=f"{old!r} -> {new!r}",
        details={"from": old, "to": new, "rows_moved": moved},
    )
    say(
        f"    renamed {old!r} -> {new!r}; child rows moved: "
        + ", ".join(f"{t}={n}" for t, n in moved.items() if n)
    )


# ── steps ────────────────────────────────────────────────────────────────────
def step_preflight(conn) -> dict:
    say("== 0. Pre-flight")
    if is_postgres():
        db = one(conn, "SELECT current_database()")[0]
        say(f"    database: {db} (Postgres)")
    else:
        say("    database: SQLite file (PAYOUT_DB) — NOT the live server database!")
    n_p = one(conn, "SELECT COUNT(*) FROM person_registry")[0]
    n_u = one(conn, "SELECT COUNT(*) FROM ev_units")[0]
    n_open = one(conn, "SELECT COUNT(*) FROM ev_assignments WHERE returned_date IS NULL")[0]
    say(f"    persons={n_p}  ev_units={n_u}  open assignments={n_open}")
    if table_exists(conn, "schema_migrations"):
        mig = one(conn, "SELECT name FROM schema_migrations ORDER BY name DESC LIMIT 1")
        say(
            f"    schema level: {mig[0] if mig else '(none recorded)'}  "
            f"(script written against 0032_head_recruiter)"
        )
    else:
        say(
            "    schema level: no schema_migrations table — an old build"
            "; the script falls back to plain SQL where needed"
        )

    cos = [r[0] for r in all_(conn, "SELECT company_name FROM companies ORDER BY company_name")]
    say(f"    companies: {', '.join(cos)}")
    jiffy = [c for c in cos if c.lower() == "jiffy"]
    spencers = [c for c in cos if c.lower().startswith("spencer")]
    if jiffy and not spencers:
        company = jiffy[0]
    elif spencers and not jiffy:
        company = spencers[0]
    elif jiffy and spencers:
        raise RuntimeError(
            f"Both {jiffy[0]!r} and {spencers[0]!r} exist "
            f"— tell me which one the placeholders go under."
        )
    else:
        raise RuntimeError(
            "Neither Jiffy nor Spencer's exists in companies — cannot place the new riders."
        )
    say(f"    placeholders will be created under company: {company!r}")

    blue = one(
        conn,
        "SELECT model_id, weekly_rate FROM ev_models WHERE LOWER(provider)='raft' "
        "AND LOWER(model_name)='blue'",
    )
    if not blue:
        raise RuntimeError("No Raft/Blue model on the rate card — new CBICEVD units need it.")
    say(
        f"    Raft/Blue model_id={blue['model_id']} "
        f"weekly_rate=Rs {int(blue['weekly_rate']) / 100:,.0f}"
    )
    return {"company": company, "blue_model_id": blue["model_id"]}


def step_trim_and_rename(conn, user: dict) -> None:
    say("\n== 1+2. EV id hygiene: trailing spaces and the two wrong ids")
    # the two wrong ids first (their stored form may carry the trailing space)
    for old_core, new, token in RENAMES:
        cands = [
            r[0] for r in all_(conn, "SELECT ev_id FROM ev_units WHERE TRIM(ev_id)=?", (old_core,))
        ]
        if ev_row(conn, new):
            h = holder(conn, new)
            say(
                f"    {new} already exists"
                + (f" (with {h['display_name']})" if h else "")
                + " — skip"
                + (f"; NOTE old id {cands[0]!r} still present!" if cands else "")
            )
            continue
        if not cands:
            say(
                f"    {old_core}: no such unit any more and {new} absent "
                f"— nothing to do (check by hand)"
            )
            continue
        if len(cands) > 1:
            raise RuntimeError(
                f"{old_core}: several units differ only by whitespace {cands!r} — stopping"
            )
        old = cands[0]
        h = holder(conn, old)
        who = (h["display_name"] or "").strip().lower() if h else ""
        if not who.startswith(token):
            raise RuntimeError(
                f"{old!r} is held by {who!r}, expected {token}* — stopping, nothing changed"
            )
        say(f"    {describe_ev(conn, old)}")
        rename_ev(conn, user, old, new)

    # anything else with stray whitespace
    stray = [r[0] for r in all_(conn, "SELECT ev_id FROM ev_units WHERE ev_id <> TRIM(ev_id)")]
    if not stray:
        say("    no other EV ids with stray spaces")
    for old in stray:
        new = old.strip()
        if ev_row(conn, new):
            say(
                f"    {old!r}: trimmed id {new!r} already exists as a separate unit "
                f"— left alone, look at it by hand"
            )
            continue
        say(f"    {describe_ev(conn, old)}")
        rename_ev(conn, user, old, new)


def step_add_new(conn, user: dict, ctx: dict) -> list[dict]:
    say("\n== 3. New Raft deployments (after 7 Sep) missing from the DB")
    company, blue = ctx["company"], ctx["blue_model_id"]
    added: list[dict] = []
    for i, (ev_id, raw_name, contact, deploy, hub, vin) in enumerate(NEW_DEPLOYMENTS):
        name = " ".join(w.capitalize() for w in raw_name.split())
        if ev_row(conn, ev_id):
            say(f"    {ev_id} {name}: unit already exists — {describe_ev(conn, ev_id)} — skip")
            continue
        conn.execute(f"SAVEPOINT item_{i}")
        try:
            existing = one(
                conn,
                "SELECT rider_id, company, person_id, name FROM rider_master "
                "WHERE mob_no=? OR rider_id=? ORDER BY is_active DESC LIMIT 1",
                (contact, contact),
            )
            if existing:
                pid = existing["person_id"]
                rid_desc = (
                    f"existing rider {existing['rider_id']}@{existing['company']} "
                    f"({existing['name']}, person {pid})"
                )
                placeholder = None
            else:
                _, placeholder, pid = insert_rider(conn, company=company, name=name, mob_no=contact)
                record_activity(
                    conn,
                    user,
                    "rider.create",
                    entity_type="rider",
                    entity_id=f"{placeholder}@{company}",
                    label=name,
                    person_id=pid,
                    details={
                        "hub": None,
                        "vehicle": "EV",
                        "bank_details": False,
                        "mob_no": contact,
                        "placeholder": True,
                        "source": f"Raft {hub} report, deployed {deploy}",
                    },
                )
                rid_desc = f"new placeholder {placeholder}@{company} (person {pid})"
            notes = (
                f"Added 2026-09-11 from Raft {hub} active-riders report "
                f"(deployed {deploy}); VIN {vin}"
            )
            conn.execute(
                "INSERT INTO ev_units (ev_id, model_id, status, notes) VALUES (?,?,'spare',?)",
                (ev_id, blue, notes),
            )
            hod = open_assignment(conn, ev_id, pid, date.fromisoformat(deploy), user["email"])
            record_activity(
                conn,
                user,
                "ev.create",
                entity_type="ev",
                entity_id=ev_id,
                label="Raft Blue",
                person_id=pid,
                details={"assigned_to": pid, "handover_date": hod, "source": f"Raft {hub} report"},
            )
            conn.execute(f"RELEASE SAVEPOINT item_{i}")
            say(f"    {ev_id} -> {name:22} {contact}  handover {hod}  via {rid_desc}")
            added.append(
                {
                    "ev_id": ev_id,
                    "name": name,
                    "contact": contact,
                    "person_id": pid,
                    "rider_id": placeholder or existing["rider_id"],
                    "handover": hod,
                }
            )
        except HTTPException as exc:
            conn.execute(f"ROLLBACK TO SAVEPOINT item_{i}")
            say(f"    {ev_id} {name}: SKIPPED — {exc.detail}")
    return added


def step_returns(conn, user: dict, ret_date: str) -> None:
    say(
        f"\n== 4. Return the EVs Raft no longer lists (returned_date {ret_date}); "
        f"keep {', '.join(KEEP)}"
    )
    for ev_id, token in RETURNS:
        u = ev_row(conn, ev_id)
        if not u:
            say(f"    {ev_id}: no such unit — skip")
            continue
        a = holder(conn, ev_id)
        if not a:
            say(f"    {ev_id}: already has no open assignment (status {u['status']}) — skip")
            continue
        who = (a["display_name"] or "").lower()
        if token not in who:
            raise RuntimeError(
                f"{ev_id} is held by {a['display_name']!r}, expected {token!r} — stopping"
            )
        say(f"    {describe_ev(conn, ev_id)}")
        close_assignment(conn, a["assignment_id"], ret_date, user["email"])
        heal = heal_backdated_return(
            conn, assignment_id=a["assignment_id"], retire=True, created_by=user["email"]
        )
        mark_pending(conn, a["assignment_id"])
        conn.execute("UPDATE ev_units SET status='returned' WHERE ev_id=?", (ev_id,))
        close_open_maintenance(conn, ev_id, ret_date)
        record_activity(
            conn,
            user,
            "ev.return",
            entity_type="ev",
            entity_id=ev_id,
            person_id=a["person_id"],
            details={
                "returned_date": ret_date,
                "from_rider": True,
                "heal": {k: v for k, v in (heal or {}).items() if k != "events"},
                "source": "Raft reconciliation 2026-09-11",
            },
        )
        summary = {k: v for k, v in (heal or {}).items() if k != "events" and v}
        say(f"        -> returned; close-out pending; heal={summary or 'nothing to reverse'}")
    for ev_id in KEEP:
        say(f"    kept: {describe_ev(conn, ev_id)}")


def step_spare(conn, user: dict) -> None:
    say(f"\n== 5. {SPARE} -> spare")
    u = ev_row(conn, SPARE)
    if not u:
        say(f"    {SPARE}: no such unit — skip")
        return
    if holder(conn, SPARE):
        raise RuntimeError(
            f"{SPARE} has an open assignment — it is not 'returned' any more; stopping"
        )
    if u["status"] == "spare":
        say(f"    {SPARE} is already spare — skip")
        return
    say(f"    {describe_ev(conn, SPARE)}")
    conn.execute("UPDATE ev_units SET status='spare' WHERE ev_id=?", (SPARE,))
    record_activity(
        conn,
        user,
        "ev.spare",
        entity_type="ev",
        entity_id=SPARE,
        details={
            "previous_status": u["status"],
            "as_of": TODAY,
            "source": "Raft reconciliation 2026-09-11",
        },
    )
    say(f"        -> {u['status']} -> spare")


def step_banti(conn, user: dict, delete_dup: bool) -> None:
    say(f"\n== 6. Banti Das ({BANTI_BAD_ID}) vs Shyamsundar Das ({BANTI_TWIN_ID})")
    for ev_id in (BANTI_BAD_ID, BANTI_TWIN_ID):
        say(f"    {describe_ev(conn, ev_id)}")
    rows = all_(
        conn,
        "SELECT pr.person_id, pr.display_name, rm.rider_id, rm.company, "
        "rm.mob_no, rm.hub, rm.is_active, "
        "       b.current_balance, ea.outstanding "
        "FROM person_registry pr "
        "LEFT JOIN rider_master rm ON rm.person_id=pr.person_id "
        "LEFT JOIN balances b ON b.person_id=pr.person_id "
        "LEFT JOIN ev_arrears ea ON ea.person_id=pr.person_id "
        "WHERE LOWER(pr.display_name) LIKE 'banti%das%' "
        "OR LOWER(pr.display_name) LIKE 'bunty%das%' "
        "   OR LOWER(pr.display_name) LIKE 'shyamsundar%' "
        "OR LOWER(pr.display_name) LIKE 'shyam sundar%' "
        "ORDER BY pr.person_id, rm.company, rm.rider_id",
    )
    say(
        "    person | name | rider id @ company | phone | hub | active | balance Rs | EV arrears Rs"
    )
    match = False
    for r in rows:
        bal = (r["current_balance"] or 0) / 100
        arr = (r["outstanding"] or 0) / 100
        phone = r["mob_no"] or ""
        flag = ""
        if (
            BANTI_TWIN_PHONE in (phone, r["rider_id"] or "")
            and "banti" in (r["display_name"] or "").lower()
        ):
            match, flag = True, "   <-- same phone Raft has for Shyamsundar Das"
        say(
            f"    {r['person_id']:>6} | {r['display_name']} | "
            f"{r['rider_id']}@{r['company']} | {phone} | "
            f"{r['hub'] or ''} | {r['is_active']} | {bal:,.0f} | {arr:,.0f}{flag}"
        )
    if match:
        say(
            "    => Banti Das carries the phone Raft lists for Shyamsundar Das: "
            "almost certainly one person."
        )
    else:
        say(
            "    => no phone match in the DB; "
            "decide from the rows above (Banti is a common pet name)."
        )
    say(
        "    Merge, if same person: web -> Riders -> Link riders, "
        "primary = Shyamsundar Das, secondary = Banti Das."
    )

    bad = ev_row(conn, BANTI_BAD_ID)
    if not bad:
        say(f"    {BANTI_BAD_ID} no longer exists — nothing to delete")
        return
    if not delete_dup:
        say(
            f"    {BANTI_BAD_ID} left untouched "
            f"(run with --banti-dup to delete this duplicate record)"
        )
        return
    a = holder(conn, BANTI_BAD_ID)
    if a and "banti" not in (a["display_name"] or "").lower():
        raise RuntimeError(
            f"{BANTI_BAD_ID} is held by {a['display_name']!r}, expected Banti Das — stopping"
        )
    refs = {}
    for t in (
        "ev_daily_ledger",
        "ev_maintenance",
        "ev_closeouts",
        "ev_closeout_reports",
        "provider_bill_lines",
    ):
        if table_exists(conn, t):
            refs[t] = one(conn, f"SELECT COUNT(*) FROM {t} WHERE ev_id=?", (BANTI_BAD_ID,))[0]
    blocking = {t: n for t, n in refs.items() if n}
    if blocking:
        raise RuntimeError(
            f"{BANTI_BAD_ID} has history rows {blocking} — not a throwaway duplicate; stopping"
        )
    n_asg = one(conn, "SELECT COUNT(*) FROM ev_assignments WHERE ev_id=?", (BANTI_BAD_ID,))[0]
    conn.execute("DELETE FROM ev_assignments WHERE ev_id=?", (BANTI_BAD_ID,))
    conn.execute("DELETE FROM ev_units WHERE ev_id=?", (BANTI_BAD_ID,))
    record_activity(
        conn,
        user,
        "ev.delete",
        entity_type="ev",
        entity_id=BANTI_BAD_ID,
        person_id=a["person_id"] if a else None,
        details={
            "reason": f"malformed duplicate of {BANTI_TWIN_ID} created 2026-09-11, never billed",
            "assignments_deleted": n_asg,
        },
    )
    say(
        f"    deleted {BANTI_BAD_ID} and its {n_asg} assignment row(s); Banti Das now holds no EV "
        f"(he gets {BANTI_TWIN_ID} through the merge)"
    )


def step_verify(conn, added: list[dict]) -> None:
    say("\n== After-state of every EV touched")
    ids = (
        [n for _, n, _ in RENAMES]
        + [e for e, *_ in NEW_DEPLOYMENTS]
        + [e for e, _ in RETURNS]
        + KEEP
        + [SPARE, BANTI_BAD_ID, BANTI_TWIN_ID]
    )
    for ev_id in ids:
        say(f"    {describe_ev(conn, ev_id)}")
    stray = one(conn, "SELECT COUNT(*) FROM ev_units WHERE ev_id <> TRIM(ev_id)")[0]
    say(f"    EV ids with stray spaces left: {stray}")
    if added:
        say("\n    New riders (give them their real Jiffy ids later with Riders -> Rename id):")
        for a in added:
            say(
                f"      {a['rider_id']:<12} {a['name']:<22} {a['contact']}  "
                f"{a['ev_id']}  from {a['handover']}"
            )
    dup = all_(
        conn,
        "SELECT person_id FROM ev_assignments WHERE returned_date IS NULL "
        "GROUP BY person_id HAVING COUNT(*)>1",
    )
    dup_ev = all_(
        conn,
        "SELECT ev_id FROM ev_assignments WHERE returned_date IS NULL "
        "GROUP BY ev_id HAVING COUNT(*)>1",
    )
    say(f"    invariants: persons with 2 open EVs = {len(dup)}, EVs with 2 holders = {len(dup_ev)}")
    if dup or dup_ev:
        raise RuntimeError("invariant violated — rolling back")


# ── main ─────────────────────────────────────────────────────────────────────
def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--apply", action="store_true", help="commit; without it everything is rolled back"
    )
    ap.add_argument(
        "--as", dest="actor", default="script:ev-fix-2026-09-11", help="actor for the activity log"
    )
    ap.add_argument("--return-date", default=TODAY, help="returned_date for step 4 (YYYY-MM-DD)")
    ap.add_argument(
        "--banti-dup", action="store_true", help="delete the duplicate CBICED0135 record"
    )
    args = ap.parse_args(argv)
    date.fromisoformat(args.return_date)  # validate
    user = {"email": args.actor, "role": "script"}

    say(
        f"EV fix 2026-09-11 — {'APPLY' if args.apply else 'DRY RUN (nothing will be saved)'}  "
        f"actor={args.actor}  return_date={args.return_date}  today(IST)={TODAY}"
    )
    conn = get_connection()
    try:
        ctx = step_preflight(conn)
        step_trim_and_rename(conn, user)
        added = step_add_new(conn, user, ctx)
        step_returns(conn, user, args.return_date)
        step_spare(conn, user)
        step_banti(conn, user, args.banti_dup)
        step_verify(conn, added)
        for n in NOTES:
            say(f"    NOTE: {n}")
        if args.apply:
            conn.commit()
            say("\nCOMMITTED.")
        else:
            conn.rollback()
            say("\nDRY RUN — rolled back, nothing saved. Re-run with --apply to commit.")
        return 0
    except Exception:
        conn.rollback()
        say("\nERROR — rolled back, nothing saved:")
        traceback.print_exc()
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
