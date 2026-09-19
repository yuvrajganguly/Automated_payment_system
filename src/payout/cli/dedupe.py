"""Delete phantom EV units and merge the duplicate people they created.

A confusable character typed into an EV id — J for I, O for zero — creates a
second EV unit that does not exist. The rider was usually re-onboarded
alongside it, so there is a second copy of the rider holding the second
vehicle. This walks both back: the phantom unit is purged, and the two copies
of the rider become one.

Run it inside the app container, which already has the database URL::

    docker exec -i payout python - < dedupe.py                      # dry run
    docker exec -i payout python - --apply < dedupe.py              # commit
    docker exec -i payout python - --apply --also-merge 12:34 < ...  # extra pairs

The dry run is the default and changes nothing. It prints every row that would
be deleted, every pair that would be merged and why, and — separately — the
pairs it refuses to merge on its own, so they can be passed back in with
``--also-merge``.

**Rent is not reversed.** Purging a phantom unit takes its ``ev_daily_ledger``
days with it, but rent already booked against the phantom rider lives in
``transactions`` / ``balances`` / ``ev_arrears``, which are keyed by person and
survive the merge. Those figures are printed so the carry-over is visible.
"""

from __future__ import annotations

import sys

from payout.db import get_connection
from payout.db.references import drop_person_singletons, purge_ev, repoint_person
from payout.domain.duplicates import (
    evidence,
    identifiers,
    name_tokens,
    norm_account,
    norm_name,
    norm_phone,
    same_name,
    same_person,
)
from payout.domain.placeholders import retire_placeholders_everywhere

# ── what we already know ─────────────────────────────────────────────────────
# (phantom ev_id, the real unit it was a typo of). The real one must exist, or
# the phantom is not a phantom and nothing is deleted.
PHANTOM_PAIRS: tuple[tuple[str, str], ...] = (
    ("CBJCEVD0250", "CBICEVD0250"),  # J for I  — Shibam Pramanick
    ("CBICEVDO286", "CBICEVD0286"),  # O for 0  — Suman Mondal
)

# Pairs confirmed by hand. Each is still re-checked below against the same
# rules as a discovered pair, so a person_id that has since changed meaning is
# skipped with a reason rather than acted on.
KNOWN_PAIRS: tuple[tuple[int, int], ...] = (
    (828, 841),  # Shibam Pramanick  — real EV / phantom EV
    (831, 840),  # Suman Mondal      — real EV / phantom EV
    (170, 171),  # SUSANTA GHOSH / Sushanta ghosh
    (747, 765),  # BIDHAN MONDAL / Bidhan Mondal
    (160, 161),  # Abhishek Tiwary / Abhishek tiwari
    (36, 124),  # Jeet Kumar Ghosh / Jeet
    (550, 589),  # Prosenjit A-1 / Prosenjit Das
)

PLACEHOLDER_PREFIX = "QSPEND"


# The matcher lives in domain/duplicates.py, because the check that runs when
# a recruiter creates a rider has to agree with the cleanup that runs after one
# slipped through. Two implementations of "is this the same man" would drift,
# and the one that drifts is always the one nobody is looking at.
# ── reading the world ────────────────────────────────────────────────────────
class Person:
    """A person plus the few facts the merge rules need."""

    def __init__(self, row) -> None:
        self.person_id = int(row["person_id"])
        self.name = row["display_name"] or ""
        self.aadhaar = norm_account(row["aadhaar_no"])
        self.pan = norm_account(row["pan_no"])
        self.phones: set[str] = set()
        self.accounts: set[str] = set()
        self.rider_ids: list[str] = []
        self.real_rider_ids: list[str] = []
        self.open_evs: list[str] = []

    @property
    def keys(self) -> set[tuple[str, str]]:
        """Hard identifiers — a shared one is what turns a name match into a
        duplicate. A name on its own never is: two men really are called
        Bidhan Mondal."""
        return identifiers(
            phones=self.phones, accounts=self.accounts, aadhaar=self.aadhaar, pan=self.pan
        )

    def __repr__(self) -> str:  # pragma: no cover - diagnostics
        return f"p{self.person_id} {self.name!r}"


def load_people(conn, phantom_evs: frozenset[str]) -> dict[int, Person]:
    """Every person, with their phones, accounts and currently-held EVs.

    Assignments on a phantom unit are ignored: the unit is about to go, so for
    the purpose of choosing which copy of a rider to keep, that side holds
    nothing.
    """
    people = {
        int(r["person_id"]): Person(r)
        for r in conn.execute(
            "SELECT person_id, display_name, aadhaar_no, pan_no FROM person_registry"
        ).fetchall()
    }
    for r in conn.execute(
        "SELECT person_id, rider_id, mob_no, account_no FROM rider_master"
    ).fetchall():
        p = people.get(int(r["person_id"]))
        if p is None:
            continue
        rid = r["rider_id"] or ""
        p.rider_ids.append(rid)
        if rid[:6].upper() != PLACEHOLDER_PREFIX:
            p.real_rider_ids.append(rid)
        if phone := norm_phone(r["mob_no"]):
            p.phones.add(phone)
        if acct := norm_account(r["account_no"]):
            p.accounts.add(acct)
    for r in conn.execute(
        "SELECT person_id, ev_id FROM ev_assignments WHERE returned_date IS NULL"
    ).fetchall():
        p = people.get(int(r["person_id"]))
        if p is not None and (r["ev_id"] or "") not in phantom_evs:
            p.open_evs.append(r["ev_id"])
    return people


# ── choosing which copy survives ─────────────────────────────────────────────
def _quality(p: Person) -> tuple:
    """Higher wins. The copy holding the vehicle is the one the office knows
    about; after that, prefer a real rider id over a QSPEND placeholder, then
    the fuller-looking name, then the older record."""
    toks = norm_name(p.name).split()
    return (
        1 if p.open_evs else 0,
        1 if p.real_rider_ids else 0,
        len(toks),
        0 if any(c.isdigit() for c in p.name) else 1,
        -p.person_id,
    )


def pick_primary(group: list[Person]) -> Person:
    return max(group, key=_quality)


# ── deciding what is a duplicate ─────────────────────────────────────────────
def shared_keys(a: Person, b: Person) -> str:
    return evidence(a.keys & b.keys)


def classify(a: Person, b: Person) -> tuple[bool, str]:
    """(merge?, reason). Two people merge when their names match AND they
    share a phone, account, Aadhaar or PAN."""
    shared = shared_keys(a, b)
    exact = same_name(a.name, b.name)
    near = same_person(a.name, b.name)
    if len(a.open_evs) and len(b.open_evs) and set(a.open_evs) != set(b.open_evs):
        return False, f"both hold an EV ({', '.join(a.open_evs)} / {', '.join(b.open_evs)})"
    if not (exact or near):
        return False, "names do not match"
    if not shared:
        return False, "same name, but no shared phone/account/Aadhaar/PAN"
    return True, f"{'same name' if exact else 'matching name'} + {shared}"


def discover(people: dict[int, Person]) -> tuple[list[tuple[int, int]], list[str]]:
    """Find duplicate pairs. Returns (pairs to merge, lines to report only).

    Candidates come from two directions — people whose names normalise the
    same, and people who share a hard identifier — so a pair is found whether
    the name or the phone is the thing that was typed twice.
    """
    by_name: dict[tuple[str, ...], list[Person]] = {}
    by_key: dict[tuple[str, str], list[Person]] = {}
    for p in people.values():
        if toks := name_tokens(p.name):
            by_name.setdefault(toks, []).append(p)
        for k in p.keys:
            by_key.setdefault(k, []).append(p)

    candidates: set[tuple[int, int]] = set()
    for bucket in (*by_name.values(), *by_key.values()):
        if len(bucket) < 2 or len(bucket) > 12:
            continue  # a 13-way bucket is a shared office phone, not one man
        for i, a in enumerate(bucket):
            for b in bucket[i + 1 :]:
                candidates.add((min(a.person_id, b.person_id), max(a.person_id, b.person_id)))

    merge: list[tuple[int, int]] = []
    report: list[str] = []
    for lo, hi in sorted(candidates):
        a, b = people[lo], people[hi]
        ok, why = classify(a, b)
        if ok:
            merge.append((lo, hi))
        else:
            # Every candidate came from a bucket, so it either shares a name or
            # shares an identifier — both are worth a human's eye even when the
            # rules below refuse to act on them.
            report.append(f"  p{lo} {a.name!r} / p{hi} {b.name!r} — {why}")
    return merge, report


def group_pairs(pairs: list[tuple[int, int]]) -> list[list[int]]:
    """Union-find, so three copies of one man become one group, not two merges
    that fight over the primary."""
    parent: dict[int, int] = {}

    def find(x: int) -> int:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups: dict[int, list[int]] = {}
    for x in parent:
        groups.setdefault(find(x), []).append(x)
    return [sorted(g) for g in groups.values() if len(g) > 1]


# ── the two write operations ─────────────────────────────────────────────────
def ev_rows(conn, ev_id: str) -> dict[str, int]:
    """How much history a unit carries, for the dry run to print."""
    counts = {}
    for table, col in (
        ("ev_assignments", "ev_id"),
        ("ev_daily_ledger", "ev_id"),
        ("ev_maintenance", "ev_id"),
        ("ev_closeouts", "ev_id"),
        ("ev_closeout_reports", "ev_id"),
    ):
        counts[table] = int(
            conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE {col}=?",  # noqa: S608 - literals above
                (ev_id,),
            ).fetchone()["n"]
        )
    counts["billed_paise"] = int(
        conn.execute(
            "SELECT COALESCE(SUM(daily_cost), 0) AS n FROM ev_daily_ledger "
            "WHERE ev_id=? AND billing_status IN ('billed', 'missed')",
            (ev_id,),
        ).fetchone()["n"]
    )
    return counts


def delete_phantom(conn, phantom: str) -> None:
    """Purge a unit. ``purge_ev`` walks ``EV_REFS``, which does not include the
    two close-out tables — they key on ``assignment_id`` — so they are cleared
    first or the DELETE on ``ev_assignments`` trips their foreign key."""
    conn.execute("DELETE FROM ev_closeouts WHERE ev_id=?", (phantom,))
    conn.execute("DELETE FROM ev_closeout_reports WHERE ev_id=?", (phantom,))
    purge_ev(conn, phantom)


def merge_person(conn, primary: int, secondary: int) -> dict:
    """Collapse secondary into primary. Mirrors ``persons.link_riders``: the
    two UNIQUE-per-person collisions are settled first, everything else is
    re-pointed through ``PERSON_REFS``, and the one-row-per-person tables are
    summed rather than moved."""
    moved: dict[str, int] = {}

    # ev_assignments is UNIQUE per person while returned_date IS NULL, so if
    # both sides still hold something, secondary's row cannot move.
    if conn.execute(
        "SELECT 1 FROM ev_assignments WHERE person_id=? AND returned_date IS NULL", (primary,)
    ).fetchone():
        conn.execute(
            "UPDATE ev_assignments SET returned_date = date('now') "
            "WHERE person_id=? AND returned_date IS NULL",
            (secondary,),
        )
    # referrals.new_person_id is UNIQUE — nobody is referred twice. Primary's
    # row is kept; the money itself is in transactions and survives.
    if conn.execute("SELECT 1 FROM referrals WHERE new_person_id=?", (primary,)).fetchone():
        conn.execute("DELETE FROM referrals WHERE new_person_id=?", (secondary,))

    repoint_person(conn, secondary, primary)
    conn.execute(
        "UPDATE referrals SET status='void', note = COALESCE(note || ' | ', '') || "
        "  'voided by person merge: referrer and referee are the same person' "
        "WHERE new_person_id=? AND referrer_person_id=? AND status <> 'void'",
        (primary, primary),
    )

    bal = conn.execute(
        "SELECT current_balance, pending_xc_rent, xc_origin_company, xc_origin_cycle_end "
        "FROM balances WHERE person_id=?",
        (secondary,),
    ).fetchone()
    if bal and (bal["current_balance"] or bal["pending_xc_rent"]):
        conn.execute(
            "INSERT OR IGNORE INTO balances (person_id, current_balance) VALUES (?, 0)", (primary,)
        )
        prim = conn.execute(
            "SELECT pending_xc_rent, xc_origin_company, xc_origin_cycle_end "
            "FROM balances WHERE person_id=?",
            (primary,),
        ).fetchone()
        xc = float(prim["pending_xc_rent"] or 0) + float(bal["pending_xc_rent"] or 0)
        conn.execute(
            "UPDATE balances SET current_balance = current_balance + ?, pending_xc_rent = ?, "
            "  xc_origin_company = ?, xc_origin_cycle_end = ? WHERE person_id=?",
            (
                bal["current_balance"] or 0,
                xc,
                (prim["xc_origin_company"] or bal["xc_origin_company"]) if xc > 0 else None,
                (prim["xc_origin_cycle_end"] or bal["xc_origin_cycle_end"]) if xc > 0 else None,
                primary,
            ),
        )
        moved["balance"] = int(bal["current_balance"] or 0)

    arr = conn.execute(
        "SELECT total_missed, total_recovered, outstanding, cod_missed, cod_recovered, "
        "       cod_outstanding FROM ev_arrears WHERE person_id=?",
        (secondary,),
    ).fetchone()
    if arr:
        conn.execute("INSERT OR IGNORE INTO ev_arrears (person_id) VALUES (?)", (primary,))
        conn.execute(
            "UPDATE ev_arrears SET total_missed = total_missed + ?, "
            "  total_recovered = total_recovered + ?, outstanding = outstanding + ?, "
            "  cod_missed = cod_missed + ?, cod_recovered = cod_recovered + ?, "
            "  cod_outstanding = cod_outstanding + ? WHERE person_id=?",
            (
                arr["total_missed"] or 0,
                arr["total_recovered"] or 0,
                arr["outstanding"] or 0,
                arr["cod_missed"] or 0,
                arr["cod_recovered"] or 0,
                arr["cod_outstanding"] or 0,
                primary,
            ),
        )
        moved["arrears_outstanding"] = int(arr["outstanding"] or 0)

    drop_person_singletons(conn, secondary)
    moved["placeholders_retired"] = len(retire_placeholders_everywhere(conn, primary))
    return moved


def carried_over(conn, person_id: int) -> str:
    """The money that follows a person into the merge, for the dry run."""
    bal = conn.execute(
        "SELECT current_balance FROM balances WHERE person_id=?", (person_id,)
    ).fetchone()
    arr = conn.execute(
        "SELECT outstanding FROM ev_arrears WHERE person_id=?", (person_id,)
    ).fetchone()
    txns = conn.execute(
        "SELECT COUNT(*) AS n FROM transactions WHERE person_id=?", (person_id,)
    ).fetchone()["n"]
    rupees = lambda v: f"{int(v or 0) / 100:,.0f}"  # noqa: E731
    return (
        f"balance {rupees(bal['current_balance'] if bal else 0)}, "
        f"arrears {rupees(arr['outstanding'] if arr else 0)}, "
        f"{int(txns)} transactions"
    )


# ── driver ───────────────────────────────────────────────────────────────────
def parse_pairs(spec: str) -> list[tuple[int, int]]:
    out = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        a, _, b = chunk.partition(":")
        out.append((int(a), int(b)))
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    apply = "--apply" in argv
    also: list[tuple[int, int]] = []
    if "--also-merge" in argv:
        also = parse_pairs(argv[argv.index("--also-merge") + 1])
    forced = {(min(a, b), max(a, b)) for a, b in also}

    say = print
    say("== dry run — nothing will change ==" if not apply else "== APPLYING ==")

    with get_connection() as conn:
        # ── 1. phantom EV units ──────────────────────────────────────────
        doomed: list[str] = []
        for phantom, real in PHANTOM_PAIRS:
            have = {
                r["ev_id"]
                for r in conn.execute(
                    "SELECT ev_id FROM ev_units WHERE ev_id IN (?, ?)", (phantom, real)
                ).fetchall()
            }
            if phantom not in have:
                say(f"\nEV {phantom}: already gone")
                continue
            if real not in have:
                say(f"\nEV {phantom}: SKIPPED — the real unit {real} does not exist, so this")
                say("   is not a typo of it. Check the id before deleting anything.")
                continue
            doomed.append(phantom)
            counts = ev_rows(conn, phantom)
            say(f"\nEV {phantom}  (phantom of {real})")
            for holder in conn.execute(
                "SELECT a.person_id, p.display_name, a.handover_date "
                "FROM ev_assignments a JOIN person_registry p ON p.person_id = a.person_id "
                "WHERE a.ev_id=?",
                (phantom,),
            ).fetchall():
                say(
                    f"   held by p{holder['person_id']} {holder['display_name']} "
                    f"since {holder['handover_date']}"
                )
            rows = ", ".join(
                f"{n} {t.replace('ev_', '')}"
                for t, n in counts.items()
                if t != "billed_paise" and n
            )
            say(f"   deleting: {rows or 'nothing but the unit row itself'}")
            if counts["billed_paise"]:
                say(
                    f"   rent booked on these days: {counts['billed_paise'] / 100:,.0f} "
                    "— NOT reversed; it stays on the rider's balance/arrears"
                )

        phantom_evs = frozenset(doomed)

        # ── 2. duplicate people ──────────────────────────────────────────
        people = load_people(conn, phantom_evs)
        found, report = discover(people)
        pairs = set(found)
        say("")
        for lo, hi in sorted({(min(a, b), max(a, b)) for a, b in KNOWN_PAIRS} | forced):
            if lo not in people or hi not in people:
                missing = [f"p{x}" for x in (lo, hi) if x not in people]
                say(f"pair p{lo}/p{hi}: skipped — {', '.join(missing)} no longer exists")
                continue
            if (lo, hi) in forced:
                pairs.add((lo, hi))
                continue
            ok, why = classify(people[lo], people[hi])
            if ok:
                pairs.add((lo, hi))
            else:
                say(f"pair p{lo}/p{hi}: skipped — {why}")

        groups = group_pairs(sorted(pairs))
        if not groups:
            say("no duplicate people to merge")
        for g in groups:
            members = [people[x] for x in g]
            primary = pick_primary(members)
            say(f"\nmerge into p{primary.person_id} {primary.name!r}")
            say(f"   keeps: {', '.join(primary.rider_ids) or 'no rider id'}")
            say(f"   {carried_over(conn, primary.person_id)}")
            for p in members:
                if p.person_id == primary.person_id:
                    continue
                _, why = classify(primary, p)
                say(f"   + p{p.person_id} {p.name!r} — {why or 'requested'}")
                say(f"     brings: {', '.join(p.rider_ids) or 'no rider id'}")
                say(f"     {carried_over(conn, p.person_id)}")

        if report:
            say("\n-- not merged, decide these yourself ------------------------")
            say("   (re-run with --also-merge a:b,c:d to include any of them)")
            for line in report:
                say(line)

        # ── 3. write ─────────────────────────────────────────────────────
        if not apply:
            # The connection's __exit__ commits on a clean exit, so a dry run
            # rolls back explicitly rather than trusting that it wrote nothing.
            conn.rollback()
            say("\n== dry run: nothing changed. Re-run with --apply ==")
            return 0

        for phantom in doomed:
            delete_phantom(conn, phantom)
            say(f"deleted EV {phantom}")
        for g in groups:
            members = [people[x] for x in g]
            primary = pick_primary(members)
            for p in members:
                if p.person_id == primary.person_id:
                    continue
                moved = merge_person(conn, primary.person_id, p.person_id)
                say(f"merged p{p.person_id} -> p{primary.person_id} {moved}")
        conn.commit()
        say("\n== committed ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
