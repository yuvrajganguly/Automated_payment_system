"""States the data should not be able to reach.

Every check here exists because something in this list actually happened and
was found weeks later, by hand, when a number looked wrong. The entry-time
checks in ``domain.duplicates`` stop new ones; this finds what is already in
the database, and what arrives through the doors that are not guarded — the
provider's own fleet file and the payout importer, which are authoritative
even when they are ugly.

The rule for adding a check: it must describe something that cannot be true,
not something that is merely unusual. "This rider has high arrears" is a
judgement and belongs on a report. "This EV was billed on a day it was in the
workshop" is a contradiction and belongs here. A page of maybes gets ignored,
and then the one real contradiction on it gets ignored too.

Each finding carries ``fix`` — what to actually do — because a list of
problems nobody knows how to action is a list nobody opens twice.
"""

from __future__ import annotations

from payout.domain.duplicates import fold_id, identifiers, norm_name, same_person

# Findings are ordered by this, worst first.
SEVERITY = {"money": 0, "identity": 1, "state": 2}


def _finding(check, severity, title, detail, fix, **extra):
    return {
        "check": check,
        "severity": severity,
        "title": title,
        "detail": detail,
        "fix": fix,
        **extra,
    }


# ── identity ─────────────────────────────────────────────────────────────────
def confusable_ev_ids(conn) -> list[dict]:
    """Two EV IDs that differ only by a character that looks like another.

    CBJCEVD0250 and CBICEVD0250 were both on file for four days before anybody
    noticed, and one of them was a vehicle that does not exist. The fold is
    done here rather than in SQL because the two backends disagree about
    ``translate`` and about the case-sensitivity of ``LIKE``.
    """
    rows = conn.execute(
        "SELECT u.ev_id, u.status, m.id_prefix, "
        "       (SELECT p.display_name FROM ev_assignments a "
        "          JOIN person_registry p ON p.person_id = a.person_id "
        "         WHERE a.ev_id = u.ev_id AND a.returned_date IS NULL LIMIT 1) AS holder "
        "FROM ev_units u JOIN ev_models m ON m.model_id = u.model_id"
    ).fetchall()
    buckets: dict[str, list] = {}
    for r in rows:
        buckets.setdefault(fold_id(r["ev_id"]), []).append(r)
    out = []
    for group in buckets.values():
        if len(group) < 2:
            continue
        ids = ", ".join(
            f"{g['ev_id']} ({g['status']}" + (f", {g['holder']}" if g["holder"] else "") + ")"
            for g in sorted(group, key=lambda g: g["ev_id"])
        )
        out.append(
            _finding(
                "confusable_ev_ids",
                "identity",
                "Two EV IDs one character apart",
                ids,
                "Work out which one is the real vehicle, move any assignment onto it, "
                "and delete the other. Rent already booked on the wrong one does not "
                "reverse itself.",
                ev_ids=[g["ev_id"] for g in group],
            )
        )
    return out


def confusable_rider_ids(conn) -> list[dict]:
    """The same fold, on rider IDs, within one company.

    ``67163_MN0W000471`` is ``67163_MNOW000471`` with a zero for a letter O.
    Across companies the same string is two different riders by design, so the
    comparison is scoped — otherwise every shared-ID arrangement (Nykaa pays
    Blitz riders under their Blitz IDs) would light this up.
    """
    rows = conn.execute("SELECT rider_id, company, person_id, name FROM rider_master").fetchall()
    buckets: dict[tuple[str, str], list] = {}
    for r in rows:
        buckets.setdefault((r["company"], fold_id(r["rider_id"])), []).append(r)
    out = []
    for (company, _), group in buckets.items():
        if len(group) < 2:
            continue
        out.append(
            _finding(
                "confusable_rider_ids",
                "identity",
                f"Two {company} rider IDs one character apart",
                ", ".join(
                    f"{g['rider_id']} (#{g['person_id']} {g['name']})"
                    for g in sorted(group, key=lambda g: g["rider_id"])
                ),
                "Check the ID against the company's own file. Rename the wrong one "
                "from the person's profile — the payout file will only ever match one "
                "of them, so the other silently stops earning.",
                person_ids=[int(g["person_id"]) for g in group],
            )
        )
    return out


def duplicate_people(conn) -> list[dict]:
    """Two person records that are the same man: matching name AND a shared
    phone, account, Aadhaar or PAN.

    Name-only pairs are deliberately absent. There are around thirty of those
    and most are two different men; putting them here would bury everything
    else. They belong in the dedupe tool's report, where a human is already
    looking at them one at a time.
    """
    people: dict[int, dict] = {}
    for r in conn.execute(
        "SELECT person_id, display_name, aadhaar_no, pan_no FROM person_registry"
    ).fetchall():
        people[int(r["person_id"])] = {
            "name": r["display_name"] or "",
            "aadhaar": r["aadhaar_no"],
            "pan": r["pan_no"],
            "phones": set(),
            "accounts": set(),
        }
    for r in conn.execute("SELECT person_id, mob_no, account_no FROM rider_master").fetchall():
        p = people.get(int(r["person_id"]))
        if p is None:
            continue
        if r["mob_no"]:
            p["phones"].add(r["mob_no"])
        if r["account_no"]:
            p["accounts"].add(r["account_no"])

    by_token: dict[str, list[int]] = {}
    for pid, p in people.items():
        for tok in set(norm_name(p["name"]).split()):
            by_token.setdefault(tok, []).append(pid)

    seen: set[tuple[int, int]] = set()
    out = []
    for bucket in by_token.values():
        if len(bucket) > 40:
            continue  # "kumar" is not evidence of anything
        for i, a in enumerate(bucket):
            for b in bucket[i + 1 :]:
                pair = (min(a, b), max(a, b))
                if pair in seen:
                    continue
                seen.add(pair)
                pa, pb = people[pair[0]], people[pair[1]]
                if not same_person(pa["name"], pb["name"]):
                    continue
                shared = identifiers(
                    phones=pa["phones"],
                    accounts=pa["accounts"],
                    aadhaar=pa["aadhaar"],
                    pan=pa["pan"],
                ) & identifiers(
                    phones=pb["phones"],
                    accounts=pb["accounts"],
                    aadhaar=pb["aadhaar"],
                    pan=pb["pan"],
                )
                if not shared:
                    continue
                out.append(
                    _finding(
                        "duplicate_people",
                        "identity",
                        "The same man twice",
                        f"#{pair[0]} {pa['name']} and #{pair[1]} {pb['name']} — "
                        + ", ".join(f"{k}={v}" for k, v in sorted(shared)),
                        "Merge them from either profile (Link Riders). The older record "
                        "keeps the history; both sets of rider IDs survive.",
                        person_ids=list(pair),
                    )
                )
    return out


# ── state ────────────────────────────────────────────────────────────────────
def ev_held_twice(conn) -> list[dict]:
    """One vehicle with two open assignments. Two men cannot ride it."""
    rows = conn.execute(
        "SELECT a.ev_id, COUNT(*) AS n, "
        "       group_concat(p.display_name) AS who "
        "FROM ev_assignments a JOIN person_registry p ON p.person_id = a.person_id "
        "WHERE a.returned_date IS NULL GROUP BY a.ev_id HAVING COUNT(*) > 1"
    ).fetchall()
    return [
        _finding(
            "ev_held_twice",
            "state",
            "One EV, two riders",
            f"{r['ev_id']} is open against {r['n']} people: {r['who']}",
            "Close the assignment that ended. Both are being charged rent for it.",
            ev_ids=[r["ev_id"]],
        )
        for r in rows
    ]


def ev_status_disagrees(conn) -> list[dict]:
    """The unit's status and its assignments say different things.

    ``status`` drives the spare pool a recruiter picks from, and the open
    assignment drives rent. When they disagree, either a vehicle nobody holds
    is invisible to the field, or one a rider is sitting on is offered to
    somebody else.
    """
    rows = conn.execute(
        "SELECT u.ev_id, u.status, "
        "       (SELECT COUNT(*) FROM ev_assignments a "
        "         WHERE a.ev_id = u.ev_id AND a.returned_date IS NULL) AS open_rows "
        "FROM ev_units u"
    ).fetchall()
    out = []
    for r in rows:
        held, status = int(r["open_rows"]) > 0, r["status"]
        if held and status != "in_use":
            detail, fix = (
                f"{r['ev_id']} is marked {status} but somebody is still holding it",
                "Either take it back properly, or mark it in use so its rent keeps running.",
            )
        elif not held and status == "in_use":
            detail, fix = (
                f"{r['ev_id']} is marked in use but nobody holds it",
                "Mark it returned or spare so the field can hand it to somebody.",
            )
        else:
            continue
        out.append(
            _finding(
                "ev_status_disagrees",
                "state",
                "EV status and assignment disagree",
                detail,
                fix,
                ev_ids=[r["ev_id"]],
            )
        )
    return out


# ── money ────────────────────────────────────────────────────────────────────
def billed_during_maintenance(conn) -> list[dict]:
    """Rent charged for a day the vehicle was in the workshop.

    The rider pays for a bike he did not have. This is money, so it is first
    on the page.
    """
    rows = conn.execute(
        "SELECT l.ev_id, COUNT(*) AS days, SUM(l.daily_cost) AS amount, "
        "       MIN(l.day) AS first_day, MAX(l.day) AS last_day, "
        "       MAX(p.display_name) AS who "
        "FROM ev_daily_ledger l "
        "JOIN ev_maintenance m ON m.ev_id = l.ev_id "
        "  AND l.day >= m.from_date AND (m.to_date IS NULL OR l.day <= m.to_date) "
        "LEFT JOIN person_registry p ON p.person_id = l.assigned_person_id "
        "WHERE l.daily_cost > 0 AND l.billing_status IN ('billed', 'missed') "
        "GROUP BY l.ev_id"
    ).fetchall()
    return [
        _finding(
            "billed_during_maintenance",
            "money",
            "Rent charged while the EV was in the workshop",
            f"{r['ev_id']}{' (' + r['who'] + ')' if r['who'] else ''}: {r['days']} day(s) "
            f"{r['first_day']}–{r['last_day']}",
            "Check the repair dates, then adjust the rider's balance from their profile. "
            "The maintenance window zeroes rent going forward, never backwards.",
            ev_ids=[r["ev_id"]],
            amount=int(r["amount"] or 0),
        )
        for r in rows
    ]


def rent_with_no_vehicle(conn) -> list[dict]:
    """EV rent booked against somebody who has never held an EV.

    Usually the tail of a duplicate: the rent went onto one copy of a man and
    the vehicle onto the other, so neither record makes sense on its own.
    """
    rows = conn.execute(
        "SELECT t.person_id, p.display_name, COUNT(*) AS n, SUM(t.amount) AS amount "
        "FROM transactions t JOIN person_registry p ON p.person_id = t.person_id "
        "WHERE t.event_type IN ('RENT', 'RENT_MISSED') "
        "  AND NOT EXISTS (SELECT 1 FROM ev_assignments a WHERE a.person_id = t.person_id) "
        "GROUP BY t.person_id, p.display_name"
    ).fetchall()
    return [
        _finding(
            "rent_with_no_vehicle",
            "money",
            "EV rent on somebody with no EV",
            f"#{r['person_id']} {r['display_name']}: {r['n']} charge(s)",
            "Look for a second copy of this person holding the vehicle, and merge them.",
            person_ids=[int(r["person_id"])],
            amount=int(r["amount"] or 0),
        )
        for r in rows
    ]


CHECKS = (
    billed_during_maintenance,
    rent_with_no_vehicle,
    confusable_ev_ids,
    confusable_rider_ids,
    duplicate_people,
    ev_held_twice,
    ev_status_disagrees,
)


def run_checks(conn) -> list[dict]:
    """Every check, worst first. A check that raises is reported as a finding
    of its own rather than taking the page down with it — a page that shows
    six of seven answers is worth more than an error."""
    out: list[dict] = []
    for check in CHECKS:
        try:
            out.extend(check(conn))
        except Exception as exc:  # noqa: BLE001 - one broken check must not hide the rest
            out.append(
                _finding(
                    check.__name__,
                    "state",
                    "This check could not run",
                    f"{check.__name__}: {exc}",
                    "Tell whoever maintains the console; the other checks below still ran.",
                )
            )
    out.sort(key=lambda f: (SEVERITY.get(f["severity"], 9), f["check"], f["detail"]))
    return out
