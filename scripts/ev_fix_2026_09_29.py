#!/usr/bin/env python
# ruff: noqa: E501 — operator script; long SQL and messages read better unwrapped
"""Raft W38 roster fixes for the LIVE database — 29 Sep 2026.

Four men, four units, from the W38 reconciliation. In ONE transaction, rolled
back unless --apply is given; each step is its own SAVEPOINT, so one failing
step is reported and the others still land.

  1. Anisur Rahaman (person 723) — our roster has him on a unit typed as
     "EV 241"; Raft bills the same vehicle as CBICEVD0241, which the DB also
     has, marked RETURNED on 11 Sep. One bike, two records. "EV 241" is folded
     INTO CBICEVD0241: its open assignment, day-ledger, maintenance and
     close-out rows move across, CBICEVD0241 goes back to in_use, "EV 241" is
     deleted. Days both records have are kept from "EV 241" (the one with the
     rider on it). The 11 Sep closed assignment on CBICEVD0241 stays as
     history.
  2. Suraj Chowdhury (person 194) — on CBICEVD0082 in the DB; Raft bills the
     vehicle as CBICEVD0282 and has since he was deployed. The unit is
     RENAMED 0082 -> 0282 (copy under the new id, re-point every child row,
     drop the old id — the FKs are not ON UPDATE CASCADE). Refused if 0082
     was ever held by anybody else, unless --force-rename: then it may be a
     real earlier unit and needs a human.
  3. Rajib Mondal (person 76, Myntra) — Raft bills CBICEVD0069 as "SHIBA
     HALDER"; the office says it is Rajib's. The unit is CREATED (Raft/Blue),
     handed over on Raft's deploy date 15 Sep, and the week's rent Raft
     billed (16–20 Sep, 5 days, ₹925 at our rate) is booked as CHARGED and
     PAID IN CASH — a RENT row and a RENT_COLLECTED row, billed day-rows,
     meter moved to 20 Sep — so the next Myntra cycle does not bill those
     days again.
  4. Timir Halder — Raft bills CBICEVD0038 (deployed 15 Sep); nobody by that
     name is on our roster. A rider record is CREATED (placeholder QSPEND id
     under --timir-company, default Myntra), the unit is created and handed
     over on 15 Sep, and the same 5 days are booked as charged and paid in
     cash. If a person whose name matches "Timir Halder" already exists the
     script uses him instead and says so.

Not touched, on purpose: CBICEVD0309 / Suman Dutta (closed), the second
Ranajit Ghosh (872 vs 826 — a person merge, do it in the console), the
damage lines.

Run inside the app container on the server (bash):

    cd /root/payout/deploy
    docker exec -i payout python - < ev_fix_2026_09_29.py                       # dry run
    docker exec -i payout python - --apply < ev_fix_2026_09_29.py               # commit
    docker exec -i payout python - --apply --timir-company Jiffy < ev_fix_2026_09_29.py

Options:
    --apply                 commit (default is a dry run that rolls back)
    --as EMAIL              who the activity log should say did this
                            (default: script:ev-fix-2026-09-29)
    --timir-company NAME    company for Timir Halder's placeholder rider id
                            (default: Myntra)
    --force-rename          rename CBICEVD0082 even if others held it before
    --skip STEP [STEP ...]  any of: anisur suraj rajib timir
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

try:
    from payout.domain.activity import record_activity as _record_activity
except ImportError:  # pragma: no cover - older image
    _record_activity = None
try:
    from payout.api.routes.evs import _open_assignment as _live_open_assignment
except ImportError:  # pragma: no cover
    _live_open_assignment = None
try:
    from payout.domain.ev_daily import backfill_billed_days as _backfill_billed_days
except ImportError:  # pragma: no cover
    _backfill_billed_days = None
try:
    from payout.domain.rent import advance_rent_charged_through as _advance_meter
except ImportError:  # pragma: no cover
    _advance_meter = None
try:
    from payout.domain.duplicates import same_person as _same_person
except ImportError:  # pragma: no cover
    try:
        from payout.domain.provider_bill import same_person as _same_person
    except ImportError:
        _same_person = None

IST = timezone(timedelta(hours=5, minutes=30))
TODAY = datetime.now(IST).date().isoformat()
NOTES: list[str] = []

# ── the facts (Raft W38 bill, 14–20 Sep 2026; W38 reconciliation of 29 Sep) ──
ANISUR = {"pid": 723, "typo_id": "EV 241", "real_id": "CBICEVD0241"}
SURAJ = {"pid": 194, "old_id": "CBICEVD0082", "new_id": "CBICEVD0282"}
RAJIB = {"pid": 76, "ev_id": "CBICEVD0069", "raft_name": "SHIBA HALDER", "deploy": "2026-09-15"}
TIMIR = {"name": "Timir Halder", "ev_id": "CBICEVD0038", "deploy": "2026-09-15"}

# The week Raft billed, and the days on it Raft charged for the two new units
# (5 days each: deployed on the 15th, handover day free, 16th–20th billed).
WEEK = ("2026-09-14", "2026-09-20")
PAID_DAYS = ("2026-09-16", "2026-09-20")
PAID_DAY_COUNT = 5
# Cycle window per company, so the rows slot into the cycle the console shows.
CYCLE_FOR = {"Myntra": ("2026-09-14", "2026-09-20"), "Jiffy": ("2026-09-15", "2026-09-21")}

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


def record_activity(conn, user, action, **kw) -> None:
    if _record_activity is None or not table_exists(conn, "activity_log"):
        note("activity feed not present on this build — actions were not logged there")
        return
    _record_activity(conn, user, action, **kw)


def open_assignment(conn, ev_id: str, pid: int, handover: date, by: str) -> str:
    """The app's own assign path (one open EV per person, unit -> in_use)."""
    if _live_open_assignment is not None:
        params = inspect.signature(_live_open_assignment).parameters
        if "by" in params:
            return _live_open_assignment(conn, ev_id, pid, handover, by)
        return _live_open_assignment(conn, ev_id, pid, handover)
    if one(
        conn, "SELECT 1 FROM ev_assignments WHERE person_id=? AND returned_date IS NULL", (pid,)
    ):
        raise HTTPException(409, "Person already has an open EV assignment")
    if one(conn, "SELECT 1 FROM ev_assignments WHERE ev_id=? AND returned_date IS NULL", (ev_id,)):
        raise HTTPException(409, "EV already assigned to someone else")
    hod = handover.isoformat()
    if has_column(conn, "ev_assignments", "assigned_by"):
        conn.execute(
            "INSERT INTO ev_assignments (person_id, ev_id, handover_date, assigned_by) VALUES (?,?,?,?)",
            (pid, ev_id, hod, by),
        )
    else:
        conn.execute(
            "INSERT INTO ev_assignments (person_id, ev_id, handover_date) VALUES (?,?,?)",
            (pid, ev_id, hod),
        )
    conn.execute("UPDATE ev_units SET status='in_use' WHERE ev_id=?", (ev_id,))
    return hod


def insert_rider(conn, *, company: str, name: str):
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
        kw["mob_no"] = None
    created, rider_id, pid = _insert_rider_into_db(conn, **kw)
    return created, rider_id, pid


def ev_row(conn, ev_id: str):
    return one(
        conn,
        "SELECT u.ev_id, u.status, u.notes, u.model_id, m.provider, m.model_name, m.weekly_rate "
        "FROM ev_units u JOIN ev_models m ON m.model_id=u.model_id WHERE u.ev_id=?",
        (ev_id,),
    )


def holder(conn, ev_id: str):
    return one(
        conn,
        "SELECT a.assignment_id, a.person_id, a.handover_date, a.rent_charged_through, "
        "       pr.display_name "
        "FROM ev_assignments a JOIN person_registry pr ON pr.person_id=a.person_id "
        "WHERE a.ev_id=? AND a.returned_date IS NULL",
        (ev_id,),
    )


def history(conn, ev_id: str):
    return all_(
        conn,
        "SELECT a.assignment_id, a.person_id, pr.display_name, a.handover_date, a.returned_date "
        "FROM ev_assignments a JOIN person_registry pr ON pr.person_id=a.person_id "
        "WHERE a.ev_id=? ORDER BY a.handover_date, a.assignment_id",
        (ev_id,),
    )


def describe_ev(conn, ev_id: str) -> str:
    u = ev_row(conn, ev_id)
    if not u:
        return f"{ev_id!r}: (no such unit)"
    h = holder(conn, ev_id)
    who = (
        f"{h['display_name']} (person {h['person_id']}) since {h['handover_date']}, "
        f"meter {h['rent_charged_through'] or '—'}"
        if h
        else "nobody"
    )
    return f"{u['ev_id']!r:16} {u['provider']}/{u['model_name']:8} {u['status']:10} -> {who}"


def person(conn, pid: int):
    return one(
        conn,
        "SELECT person_id, display_name, deduction_company, deduction_rider_id "
        "FROM person_registry WHERE person_id=?",
        (pid,),
    )


def raft_blue_model_id(conn) -> int:
    row = one(
        conn,
        "SELECT model_id FROM ev_models WHERE provider='Raft' AND model_name='Blue' "
        + ("AND COALESCE(is_active,1)=1 " if has_column(conn, "ev_models", "is_active") else "")
        + "ORDER BY model_id LIMIT 1",
    )
    if not row:
        raise RuntimeError("no active Raft/Blue row in ev_models — cannot create units")
    return int(row["model_id"])


def create_unit(conn, user, ev_id: str, model_id: int, notes: str) -> None:
    conn.execute(
        "INSERT INTO ev_units (ev_id, model_id, status, notes) VALUES (?,?,'spare',?)",
        (ev_id, model_id, notes),
    )
    record_activity(
        conn,
        user,
        "ev.create",
        entity_type="ev",
        entity_id=ev_id,
        label=ev_id,
        details={"notes": notes},
    )


def deduction_for(conn, pid: int, fallback_company: str) -> tuple[str, str]:
    """(company, rider_id) the rent rows should carry — the person's deduction
    anchor, else his first active rider id at the fallback company, else any."""
    pr = person(conn, pid)
    if pr and pr["deduction_company"] and pr["deduction_rider_id"]:
        return pr["deduction_company"], pr["deduction_rider_id"]
    row = one(
        conn,
        "SELECT company, rider_id FROM rider_master WHERE person_id=? AND company=? "
        "ORDER BY COALESCE(is_active,1) DESC, rider_id LIMIT 1",
        (pid, fallback_company),
    ) or one(
        conn,
        "SELECT company, rider_id FROM rider_master WHERE person_id=? "
        "ORDER BY COALESCE(is_active,1) DESC, rider_id LIMIT 1",
        (pid,),
    )
    if not row:
        raise RuntimeError(f"person {pid} has no rider id at all")
    return row["company"], row["rider_id"]


def book_cash_rent(conn, user, pid: int, ev_id: str, company_hint: str, why: str) -> None:
    """Charge the 5 days Raft billed and record that the rider paid them in
    cash: RENT and RENT_COLLECTED for the week, billed day-rows, meter to the
    20th. The balance is untouched — the two rows net to zero, exactly as a
    payout deduction would have."""
    u = ev_row(conn, ev_id)
    weekly = int(u["weekly_rate"])
    amount = round(weekly * PAID_DAY_COUNT / 7)  # paise, same rounding as the engine
    company, rider_id = deduction_for(conn, pid, company_hint)
    cs, ce = CYCLE_FOR.get(company, WEEK)
    already = one(
        conn,
        "SELECT id FROM transactions WHERE person_id=? AND event_type='RENT' "
        "AND cycle_start=? AND cycle_end=? AND remarks LIKE ?",
        (pid, cs, ce, f"%{ev_id}%"),
    )
    if already:
        say(f"    rent for {cs}..{ce} already booked on {ev_id} (txn {already['id']}) — skipped")
        return
    bal = one(conn, "SELECT current_balance FROM balances WHERE person_id=?", (pid,))
    balance = bal["current_balance"] if bal else 0
    rent_id = conn.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, days, remarks, created_by) "
        "VALUES (?,?,?,?,?,'RENT',?,?,?,?,?)",
        (
            pid,
            rider_id,
            company,
            cs,
            ce,
            -amount,
            balance,
            PAID_DAY_COUNT,
            f"Rent {PAID_DAYS[0]}..{PAID_DAYS[1]} on {ev_id} ({PAID_DAY_COUNT} days, Raft W38) — {why}",
            user["email"],
        ),
    ).lastrowid
    conn.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after, days, remarks, created_by) "
        "VALUES (?,?,?,?,?,'RENT_COLLECTED',?,?,?,?,?)",
        (
            pid,
            rider_id,
            company,
            cs,
            ce,
            amount,
            balance,
            PAID_DAY_COUNT,
            f"Paid in cash (Raft W38 fix, {ev_id}) — {why}",
            user["email"],
        ),
    )
    if _backfill_billed_days is not None:
        made = _backfill_billed_days(
            conn, person_id=pid, event_id=rent_id, day_from=PAID_DAYS[0], day_to=PAID_DAYS[1]
        )
    else:
        made = 0
        note("backfill_billed_days not on this build — day-rows for the cash rent were not written")
    if _advance_meter is not None:
        _advance_meter(conn, pid, PAID_DAYS[1])
    else:
        conn.execute(
            "UPDATE ev_assignments SET rent_charged_through=? WHERE person_id=? AND returned_date IS NULL",
            (PAID_DAYS[1], pid),
        )
    record_activity(
        conn,
        user,
        "ledger.rent_cash",
        entity_type="person",
        entity_id=pid,
        label=f"{ev_id}: ₹{amount / 100:,.0f} for {PAID_DAY_COUNT} days, paid in cash",
        details={
            "ev_id": ev_id,
            "amount_paise": amount,
            "days": PAID_DAY_COUNT,
            "rent_txn": rent_id,
        },
    )
    say(
        f"    booked RENT −₹{amount / 100:,.0f} and RENT_COLLECTED +₹{amount / 100:,.0f} "
        f"({company}/{rider_id}, cycle {cs}..{ce}); {made} billed day-row(s); meter -> {PAID_DAYS[1]}"
    )


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
def step_preflight(conn) -> None:
    say("== 0. Pre-flight")
    say(f"    backend: {'PostgreSQL' if is_postgres() else 'SQLite'}")
    for ev in (
        ANISUR["typo_id"],
        ANISUR["real_id"],
        SURAJ["old_id"],
        SURAJ["new_id"],
        RAJIB["ev_id"],
        TIMIR["ev_id"],
    ):
        say("    " + describe_ev(conn, ev))
    for pid in (ANISUR["pid"], SURAJ["pid"], RAJIB["pid"]):
        p = person(conn, pid)
        say(
            f"    person {pid}: "
            + (
                f"{p['display_name']} (deducts at {p['deduction_company']}/{p['deduction_rider_id']})"
                if p
                else "MISSING"
            )
        )
    missing = [
        n
        for n, f in (
            ("record_activity", _record_activity),
            ("_open_assignment", _live_open_assignment),
            ("backfill_billed_days", _backfill_billed_days),
            ("advance_rent_charged_through", _advance_meter),
            ("same_person", _same_person),
        )
        if f is None
    ]
    if missing:
        note(
            "this build lacks: "
            + ", ".join(missing)
            + " — the script falls back to plain SQL there"
        )


def step_anisur(conn, user: dict) -> None:
    say(f"== 1. Anisur Rahaman: fold {ANISUR['typo_id']!r} into {ANISUR['real_id']!r}")
    typo, real, pid = ANISUR["typo_id"], ANISUR["real_id"], ANISUR["pid"]
    if not ev_row(conn, typo):
        h = holder(conn, real)
        if h and int(h["person_id"]) == pid:
            say("    already done — nothing to do")
            return
        raise RuntimeError(
            f"{typo!r} is gone but {real!r} is not on person {pid}; look before running again"
        )
    if not ev_row(conn, real):
        raise RuntimeError(
            f"{real!r} does not exist — this was meant to be a merge, not a rename; stop"
        )
    h_typo, h_real = holder(conn, typo), holder(conn, real)
    if not h_typo or int(h_typo["person_id"]) != pid:
        raise RuntimeError(
            f"{typo!r} is not held by person {pid} — got {dict(h_typo) if h_typo else None}"
        )
    if h_real:
        raise RuntimeError(
            f"{real!r} still has an open assignment ({dict(h_real)}) — not the returned unit we expected"
        )
    last = history(conn, real)
    if last and int(last[-1]["person_id"]) != pid:
        raise RuntimeError(
            f"{real!r}'s last holder was person {last[-1]['person_id']}, not {pid}; stop"
        )
    say("    " + describe_ev(conn, typo))
    say("    " + describe_ev(conn, real))
    u_typo, u_real = ev_row(conn, typo), ev_row(conn, real)
    if u_typo["model_id"] != u_real["model_id"]:
        note(
            f"{typo!r} was {u_typo['provider']}/{u_typo['model_name']} (₹{int(u_typo['weekly_rate']) / 100:,.0f}) and "
            f"{real!r} is {u_real['provider']}/{u_real['model_name']} (₹{int(u_real['weekly_rate']) / 100:,.0f}); "
            "rent already charged stays as charged, from here the rate is CBICEVD0241's"
        )
    # Days both records carry: the typo record's day is the one with the rider
    # on it (the other side was rewritten 'unassigned' by the 11 Sep return).
    overlap = all_(
        conn,
        "SELECT t.day FROM ev_daily_ledger t JOIN ev_daily_ledger r ON r.day=t.day AND r.ev_id=? "
        "WHERE t.ev_id=? ORDER BY t.day",
        (real, typo),
    )
    if overlap:
        days = [r["day"] for r in overlap]
        conn.execute(
            f"DELETE FROM ev_daily_ledger WHERE ev_id=? AND day IN ({','.join('?' * len(days))})",
            (real, *days),
        )
        say(
            f"    {len(days)} overlapping day-row(s) on {real!r} replaced by {typo!r}'s: {days[0]}..{days[-1]}"
        )
    moved = {}
    for t in EV_CHILD_TABLES:
        if table_exists(conn, t):
            moved[t] = conn.execute(f"UPDATE {t} SET ev_id=? WHERE ev_id=?", (real, typo)).rowcount
    conn.execute("UPDATE ev_units SET status='in_use' WHERE ev_id=?", (real,))
    conn.execute("DELETE FROM ev_units WHERE ev_id=?", (typo,))
    record_activity(
        conn,
        user,
        "ev.merge",
        entity_type="ev",
        entity_id=real,
        label=f"{typo!r} folded into {real!r} (same vehicle; Raft W38)",
        details={"from": typo, "to": real, "rows_moved": moved, "overlap_days": len(overlap)},
    )
    say("    moved: " + ", ".join(f"{t}={n}" for t, n in moved.items() if n))
    say("    now: " + describe_ev(conn, real))


def step_suraj(conn, user: dict, force: bool) -> None:
    say(f"== 2. Suraj Chowdhury: rename {SURAJ['old_id']!r} -> {SURAJ['new_id']!r}")
    old, new, pid = SURAJ["old_id"], SURAJ["new_id"], SURAJ["pid"]
    if ev_row(conn, new) and not ev_row(conn, old):
        h = holder(conn, new)
        say("    already done — " + describe_ev(conn, new))
        if not h or int(h["person_id"]) != pid:
            note(f"{new!r} exists but is not on person {pid}")
        return
    if not ev_row(conn, old):
        raise RuntimeError(f"{old!r} does not exist")
    if ev_row(conn, new):
        raise RuntimeError(
            f"{new!r} already exists too — two records for one vehicle; needs a merge, not a rename"
        )
    h = holder(conn, old)
    if not h or int(h["person_id"]) != pid:
        raise RuntimeError(f"{old!r} is not held by person {pid} — got {dict(h) if h else None}")
    others = [r for r in history(conn, old) if int(r["person_id"]) != pid]
    say("    " + describe_ev(conn, old))
    for r in history(conn, old):
        say(
            f"      history: {r['display_name']} ({r['person_id']}) {r['handover_date']} -> {r['returned_date'] or 'open'}"
        )
    if others and not force:
        raise RuntimeError(
            f"{old!r} was held by {len(others)} other rider(s) before Suraj — it may be a real unit "
            "and Raft's 0282 a different one. Re-run with --force-rename if you are sure it is a typo."
        )
    rename_ev(conn, user, old, new)


def step_rajib(conn, user: dict, model_id: int) -> None:
    say(
        f"== 3. Rajib Mondal ({RAJIB['pid']}): create {RAJIB['ev_id']!r}, hand over, book the cash rent"
    )
    pid, ev = RAJIB["pid"], RAJIB["ev_id"]
    if not person(conn, pid):
        raise RuntimeError(f"person {pid} missing")
    if ev_row(conn, ev):
        say("    unit exists — " + describe_ev(conn, ev))
    else:
        create_unit(
            conn,
            user,
            ev,
            model_id,
            f"Raft W38 bill line, deployed {RAJIB['deploy']} (Raft has it as {RAJIB['raft_name']})",
        )
        say(f"    created {ev!r} (Raft/Blue)")
    h = holder(conn, ev)
    if h and int(h["person_id"]) == pid:
        say("    already assigned")
    else:
        mine = one(
            conn,
            "SELECT ev_id FROM ev_assignments WHERE person_id=? AND returned_date IS NULL",
            (pid,),
        )
        if mine:
            raise RuntimeError(
                f"person {pid} already holds {mine['ev_id']!r} — a person has one open unit; stop"
            )
        open_assignment(conn, ev, pid, date.fromisoformat(RAJIB["deploy"]), user["email"])
        record_activity(
            conn,
            user,
            "ev.assign",
            entity_type="ev",
            entity_id=ev,
            label=f"-> person {pid} from {RAJIB['deploy']}",
            details={"person_id": pid},
        )
        say(f"    handed over to {pid} on {RAJIB['deploy']}")
    book_cash_rent(conn, user, pid, ev, "Myntra", "office confirmed Rajib paid the week's rent")
    say("    now: " + describe_ev(conn, ev))


def step_timir(conn, user: dict, model_id: int, company: str) -> None:
    say(f"== 4. Timir Halder: create rider + {TIMIR['ev_id']!r}, hand over, book the cash rent")
    ev = TIMIR["ev_id"]
    pid = None
    if _same_person is not None:
        hits = [
            r
            for r in all_(conn, "SELECT person_id, display_name FROM person_registry")
            if _same_person(r["display_name"], TIMIR["name"])
        ]
        if len(hits) == 1:
            pid = int(hits[0]["person_id"])
            say(f"    a person already matches: {hits[0]['display_name']} ({pid}) — using him")
        elif len(hits) > 1:
            raise RuntimeError(
                "more than one person matches 'Timir Halder': "
                + ", ".join(f"{r['display_name']} ({r['person_id']})" for r in hits)
            )
    if pid is None:
        h = holder(conn, ev) if ev_row(conn, ev) else None
        if h:
            pid = int(h["person_id"])
            say(f"    {ev!r} already on {h['display_name']} ({pid})")
        else:
            created, rider_id, pid = insert_rider(conn, company=company, name=TIMIR["name"])
            say(f"    created person {pid} with placeholder id {rider_id!r} at {company}")
            note(
                f"Timir Halder is person {pid} under placeholder {rider_id!r} at {company} — give him his real id (Riders -> Rename id) and a hub"
            )
    if ev_row(conn, ev):
        say("    unit exists — " + describe_ev(conn, ev))
    else:
        create_unit(conn, user, ev, model_id, f"Raft W38 bill line, deployed {TIMIR['deploy']}")
        say(f"    created {ev!r} (Raft/Blue)")
    h = holder(conn, ev)
    if h and int(h["person_id"]) == pid:
        say("    already assigned")
    else:
        mine = one(
            conn,
            "SELECT ev_id FROM ev_assignments WHERE person_id=? AND returned_date IS NULL",
            (pid,),
        )
        if mine:
            raise RuntimeError(f"person {pid} already holds {mine['ev_id']!r}; stop")
        open_assignment(conn, ev, pid, date.fromisoformat(TIMIR["deploy"]), user["email"])
        record_activity(
            conn,
            user,
            "ev.assign",
            entity_type="ev",
            entity_id=ev,
            label=f"-> person {pid} from {TIMIR['deploy']}",
            details={"person_id": pid},
        )
        say(f"    handed over to {pid} on {TIMIR['deploy']}")
    book_cash_rent(conn, user, pid, ev, company, "office confirmed Timir paid the week's rent")
    say("    now: " + describe_ev(conn, ev))


def step_verify(conn) -> None:
    say("== 5. After")
    for ev in (ANISUR["real_id"], SURAJ["new_id"], RAJIB["ev_id"], TIMIR["ev_id"]):
        say("    " + describe_ev(conn, ev))
    for ev in (ANISUR["typo_id"], SURAJ["old_id"]):
        say(f"    {ev!r}: {'still exists!' if ev_row(conn, ev) else 'gone'}")
    rows = all_(
        conn,
        "SELECT person_id, event_type, amount, days, cycle_start, cycle_end, remarks FROM transactions "
        "WHERE remarks LIKE '%Raft W38%' ORDER BY id",
    )
    for r in rows:
        say(
            f"    txn {r['person_id']} {r['event_type']:15} ₹{r['amount'] / 100:>9,.2f} {r['days'] or ''} {r['cycle_start']}..{r['cycle_end']}  {r['remarks'][:70]}"
        )


# ── main ─────────────────────────────────────────────────────────────────────
STEPS = ("anisur", "suraj", "rajib", "timir")


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--apply", action="store_true", help="commit; without it everything is rolled back"
    )
    ap.add_argument(
        "--as", dest="actor", default="script:ev-fix-2026-09-29", help="actor for the activity log"
    )
    ap.add_argument(
        "--timir-company", default="Myntra", help="company for Timir Halder's placeholder id"
    )
    ap.add_argument(
        "--force-rename", action="store_true", help="rename CBICEVD0082 even if others held it"
    )
    ap.add_argument("--skip", nargs="*", default=[], choices=STEPS, help="steps to leave alone")
    args = ap.parse_args(argv)
    user = {"email": args.actor, "role": "script"}

    say(
        f"EV fix 2026-09-29 — {'APPLY' if args.apply else 'DRY RUN (nothing will be saved)'}  actor={args.actor}  today(IST)={TODAY}"
    )
    conn = get_connection()
    failed: list[str] = []
    try:
        step_preflight(conn)
        model_id = raft_blue_model_id(conn)
        plan = [
            ("anisur", lambda: step_anisur(conn, user)),
            ("suraj", lambda: step_suraj(conn, user, args.force_rename)),
            ("rajib", lambda: step_rajib(conn, user, model_id)),
            ("timir", lambda: step_timir(conn, user, model_id, args.timir_company)),
        ]
        for name, fn in plan:
            if name in args.skip:
                say(f"== {name}: skipped")
                continue
            conn.execute(f"SAVEPOINT s_{name}")
            try:
                fn()
                conn.execute(f"RELEASE SAVEPOINT s_{name}")
            except Exception as e:  # noqa: BLE001 — report, roll this step back, carry on
                conn.execute(f"ROLLBACK TO SAVEPOINT s_{name}")
                failed.append(name)
                say(f"    FAILED, rolled back this step only: {e}")
        step_verify(conn)
        for n in NOTES:
            say(f"    NOTE: {n}")
        if failed:
            say(f"\n{len(failed)} step(s) did not land: {', '.join(failed)}")
        if args.apply:
            conn.commit()
            say("\nCOMMITTED" + (" (the failed steps are not in it)." if failed else "."))
        else:
            conn.rollback()
            say("\nDRY RUN — rolled back, nothing saved. Re-run with --apply to commit.")
        return 1 if failed else 0
    except Exception:
        conn.rollback()
        say("\nERROR — rolled back, nothing saved:")
        traceback.print_exc()
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
