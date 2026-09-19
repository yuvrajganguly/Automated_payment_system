"""Telling two records of the same person or vehicle from two real ones.

One implementation, used in three places that must agree: the checks that run
when a recruiter creates a rider or an EV, the anomalies page that lists what
slipped through before those checks existed, and ``cli.dedupe``, which cleans
up what is already in the database.

Two separate problems live here.

**Confusable characters.** ``CBJCEVD0250`` is ``CBICEVD0250`` with a J for an
I, and ``CBICEVDO286`` is ``CBICEVD0286`` with a letter O for a zero. Both were
typed in the field in September 2026, both created a vehicle that does not
exist, and neither was noticed until a provider bill was reconciled six weeks
later. Folding the confusable pairs together turns "spot the difference" into
string equality.

**The same man written twice.** Names arrive from three sources — the office,
the recruiter app, the company's own payout file — and agree on spelling only
by luck: SUSANTA GHOSH and Sushanta ghosh are one man. But a name on its own
never establishes that: two different men really are both called Bidhan Mondal,
and merging them pools their money with no clean way back. So a name match is
only ever half the evidence; the other half is a shared phone, account,
Aadhaar or PAN.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher

# Characters that look alike in a handwritten or hurriedly-typed ID, folded to
# one representative each. Digits win over letters because the IDs in question
# are mostly digits after a fixed prefix.
CONFUSABLES = str.maketrans(
    {
        "O": "0",
        "Q": "0",
        "D": "0",  # only ever seen inside a numeric tail; see fold_id
        "I": "1",
        "J": "1",
        "L": "1",
        "S": "5",
        "B": "8",
        "Z": "2",
    }
)

# The same map minus the letters that legitimately appear in our ID prefixes
# (CBICEVD, KOL). Folding those would make every Raft Blue ID collide with
# every other one, which is worse than useless.
_PREFIX_SAFE = str.maketrans({"O": "0", "Q": "0", "I": "1", "J": "1", "L": "1", "S": "5"})


def fold_id(value: str | None, prefix: str | None = None) -> str:
    """An ID reduced to what it would look like if every confusable character
    had been typed the other way.

    ``prefix`` is the model's known ID prefix. Everything up to its length is
    left alone — those letters are meant to be letters — and only the tail is
    folded. Without a prefix the whole string is folded with the safer map,
    which still catches O-for-0 and J-for-I but leaves D and B alone so that
    ``CBICEVD`` does not turn into ``C81CEV0``.
    """
    v = (value or "").strip().upper()
    if not v:
        return ""
    if prefix:
        p = prefix.strip().upper()
        if v.startswith(p):
            return p + v[len(p) :].translate(CONFUSABLES)
    return v.translate(_PREFIX_SAFE)


# ── names ────────────────────────────────────────────────────────────────────
def norm_name(name: str | None) -> str:
    """Lowercase, punctuation to spaces, whitespace collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (name or "").lower())).strip()


def name_tokens(name: str | None) -> tuple[str, ...]:
    return tuple(sorted(norm_name(name).split()))


def same_name(a: str | None, b: str | None) -> bool:
    """The same name written the same way, ignoring case, punctuation, and the
    order the parts were typed in."""
    ta = name_tokens(a)
    return bool(ta) and ta == name_tokens(b)


def same_person(a: str | None, b: str | None) -> bool:
    """One name is plausibly the other, allowing spelling drift and dropped
    parts: Susanta/Sushanta, Tiwary/Tiwari, "Jeet" for "Jeet Kumar Ghosh".

    Every token of the shorter name must pair off with a *distinct* token of
    the longer one at 0.75 similarity or better. There is deliberately no list
    of common surnames: an earlier version had one, and matching on a shared
    surname alone made Somnath Sardar and Milon Sardar the same man.
    """
    ta, tb = norm_name(a).split(), norm_name(b).split()
    if not ta or not tb:
        return False
    if sorted(ta) == sorted(tb):
        return True
    short, long = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    spare = list(long)
    for tok in short:
        best, at = 0.0, None
        for i, other in enumerate(spare):
            r = SequenceMatcher(None, tok, other).ratio()
            if r > best:
                best, at = r, i
        if best < 0.75 or at is None:
            return False
        spare.pop(at)
    return True


# ── hard identifiers ─────────────────────────────────────────────────────────
def norm_phone(value: str | None) -> str:
    """Last ten digits, so +91, 0 and spacing all compare equal. Anything
    shorter than ten digits is not a phone number and matches nothing."""
    digits = re.sub(r"\D", "", value or "")
    return digits[-10:] if len(digits) >= 10 else ""


def norm_account(value: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def identifiers(
    *,
    phones: object = (),
    accounts: object = (),
    aadhaar: str | None = None,
    pan: str | None = None,
) -> set[tuple[str, str]]:
    """The set of hard identifiers a person carries, as (kind, value) pairs.

    A shared one is what turns a name match into a duplicate. Blank values are
    dropped rather than kept as empty strings: two people who both have no
    phone number do not thereby share a phone number.
    """
    out: set[tuple[str, str]] = set()
    for raw in phones or ():
        if p := norm_phone(raw):
            out.add(("phone", p))
    for raw in accounts or ():
        if a := norm_account(raw):
            out.add(("account", a))
    if a := norm_account(aadhaar):
        out.add(("aadhaar", a))
    if p := norm_account(pan):
        out.add(("pan", p))
    return out


def evidence(shared: set[tuple[str, str]]) -> str:
    """Shared identifiers, written out for a human to read."""
    return ", ".join(f"{kind}={value}" for kind, value in sorted(shared))


__all__ = [
    "CONFUSABLES",
    "EvIdProblem",
    "check_ev_id",
    "evidence",
    "find_duplicate_people",
    "fold_id",
    "identifiers",
    "name_tokens",
    "norm_account",
    "norm_name",
    "norm_phone",
    "same_name",
    "same_person",
]


# ── EV IDs ───────────────────────────────────────────────────────────────────
class EvIdProblem(Exception):
    """A new EV ID that should not be created. ``args[0]`` is the sentence a
    recruiter sees, so it names the ID it collides with or the prefix it
    breaks — "invalid" on its own tells a man in the field nothing."""


def check_ev_id(new_id: str, prefix: str | None, existing: object) -> None:
    """Raise ``EvIdProblem`` if ``new_id`` cannot be a real vehicle.

    ``existing`` is every unit already on file as ``(ev_id, id_prefix)`` pairs.
    Two passes, because one fold cannot catch both shapes:

    * a **global** fold, which leaves the letters that appear in our prefixes
      alone and catches the common slips — O for 0, J for I, L for 1. This is
      what would have caught both September phantoms;
    * a **tail** fold within the model's own prefix, which can be more
      aggressive (D for 0, B for 8) because the prefix is held fixed, so
      CBICEVD does not fold into itself.

    An ID that merely *reuses* an existing one is left to the caller's own
    UNIQUE check — that is a different message ("already exists"), and this
    one should not claim the ID looks like a typo when it is exact.
    """
    candidate = (new_id or "").strip().upper()
    if not candidate:
        raise EvIdProblem("An EV ID is required.")
    if prefix and not candidate.startswith(prefix.strip().upper()):
        raise EvIdProblem(
            f"{candidate} does not start with {prefix.strip().upper()}, which is what "
            f"this model's IDs look like. Check the ID on the vehicle — a single "
            f"wrong letter creates a second vehicle that does not exist."
        )
    mine_global, mine_tail = fold_id(candidate), fold_id(candidate, prefix)
    for row in existing or ():
        other, other_prefix = (row[0] or "").strip().upper(), (row[1] if len(row) > 1 else None)
        if not other or other == candidate:
            continue  # exact duplicates are the caller's UNIQUE check, not ours
        same_model = (prefix or "") == (other_prefix or "")
        if fold_id(other) == mine_global or (same_model and fold_id(other, prefix) == mine_tail):
            raise EvIdProblem(
                f"{candidate} is one character away from {other}, which already exists — "
                f"the difference is a character that looks like another (O and 0, I and J, "
                f"L and 1). If this really is a different vehicle, tell the office."
            )


# ── people ───────────────────────────────────────────────────────────────────
def find_duplicate_people(
    conn,
    name: str | None,
    *,
    phones: object = (),
    accounts: object = (),
    aadhaar: str | None = None,
    pan: str | None = None,
    exclude_person_id: int | None = None,
) -> list[dict]:
    """People already on file who look like the person about to be created.

    Each hit carries ``strong``: the name matches **and** they share a phone,
    account, Aadhaar or PAN. That is the pair we refuse to create twice. A
    name-only hit is ``strong=False`` — worth showing the recruiter, never
    worth blocking on, because two men called Bidhan Mondal is an ordinary
    Tuesday and refusing the second one would strand a real rider in the field.

    Deliberately **not scoped to a company**. The check that shipped before
    this one was per-company, and that is exactly how Suman Mondal ended up
    twice: the office had him at Jiffy and the recruiter added him at Myntra,
    so the two records never met. A person is a person at every company.

    Ordering puts strong matches first, then the older record, so a caller
    taking hits[0] gets the one most likely to be the real him.
    """
    wanted_tokens = set(norm_name(name).split())
    if not wanted_tokens:
        return []
    wanted_keys = identifiers(phones=phones, accounts=accounts, aadhaar=aadhaar, pan=pan)

    people: dict[int, dict] = {}
    for r in conn.execute(
        "SELECT person_id, display_name, aadhaar_no, pan_no FROM person_registry"
    ).fetchall():
        pid = int(r["person_id"])
        if pid == exclude_person_id:
            continue
        people[pid] = {
            "person_id": pid,
            "display_name": r["display_name"] or "",
            "phones": set(),
            "accounts": set(),
            "aadhaar": r["aadhaar_no"],
            "pan": r["pan_no"],
            "rider_ids": [],
        }
    for r in conn.execute(
        "SELECT person_id, rider_id, company, mob_no, account_no FROM rider_master"
    ).fetchall():
        p = people.get(int(r["person_id"]))
        if p is None:
            continue
        p["rider_ids"].append(f"{r['rider_id']}@{r['company']}")
        if r["mob_no"]:
            p["phones"].add(r["mob_no"])
        if r["account_no"]:
            p["accounts"].add(r["account_no"])

    hits: list[dict] = []
    for p in people.values():
        # Cheap gate before the fuzzy comparison: a real match always shares at
        # least one whole name token. Susanta/Sushanta differ, but Ghosh does
        # not, and "Jeet" is itself a token of "Jeet Kumar Ghosh".
        if not wanted_tokens & set(norm_name(p["display_name"]).split()) and not wanted_keys:
            continue
        if not same_person(name, p["display_name"]):
            continue
        shared = wanted_keys & identifiers(
            phones=p["phones"], accounts=p["accounts"], aadhaar=p["aadhaar"], pan=p["pan"]
        )
        hits.append(
            {
                "person_id": p["person_id"],
                "display_name": p["display_name"],
                "rider_ids": sorted(p["rider_ids"]),
                "strong": bool(shared),
                "evidence": evidence(shared) if shared else "same name only",
            }
        )
    hits.sort(key=lambda h: (not h["strong"], h["person_id"]))
    return hits
