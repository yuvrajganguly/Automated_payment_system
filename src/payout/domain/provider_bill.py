"""Reconcile a provider's weekly bill against our own books.

Every week Raft sends one line per vehicle — their id, the VIN, the rider's
name as they have it, the amount, a remark. The question each line asks is the
same: *did we charge somebody for this, and did they pay?* Answering it by hand
took an afternoon and the answers were then lost in a spreadsheet, so this is
that afternoon written down.

Five rules were learned the hard way, reconciling week 36 by hand, and each one
exists here because getting it wrong understated what we had collected:

**Arrears recovered is collected.** Where the ledger booked ``RENT_MISSED`` and
then ``RENT_RECOVERED`` for the same person in the same week, the money came
in. It came out of arrears instead of that week's payout, but it came in.
Reading the two columns separately made a settled week look like a debt.

**A person billed for two units gets their charge split, not repeated.** One
rider carried ``RENT 2500`` across two vehicles; printing 2500 against both
doubled him. Split pro rata by what each unit should have cost.

**Expected is our daily rate times the days billed.** Not our weekly rate
scaled by the provider's amount, and not zero just because the unit came back:
a vehicle out for three days earns three days of rent whatever happened after.

**The days come from the bill, not from our assignment dates.** Handover and
return dates are exactly the thing that goes wrong, so they cannot be the
denominator. The provider's own full-week amount — the modal figure in the bill
they just sent — divided by seven gives their daily rate, and their amount
divided by that gives the days. It self-calibrates every week.

**What the office knows beats what the tables know.** Which vehicles actually
came back, which rider is really on a unit, that two person records are one
man: none of it is derivable, and guessing produces a report that is
confidently wrong somewhere new each week. So every computed field can be
overridden, and the override is keyed to the vehicle so it survives into next
week's bill.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from datetime import date, timedelta
from difflib import SequenceMatcher
from typing import Any

# One word per line. The office reads this column down the page and hands the
# page to somebody else; anything longer stopped being read.
TAGS = (
    "Collected",
    "Partial",
    "Not collected",
    "Returned",
    "Swap",
    "Charged",
    "Paid Manually",
    "Reversed",
    "Damage",
)

# Fields the office may correct on a line. Anything else is rejected, so a typo
# in an API call cannot quietly invent a column.
OVERRIDE_FIELDS = ("tag", "rider", "person_id", "expected", "charged", "collected", "note")


def _norm(name: str | None) -> str:
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z ]", " ", n.lower()).split())


def same_person(a: str | None, b: str | None) -> bool:
    """Do these two names describe the same man?

    Every token has to pair off. Raft and we transliterate Bengali names
    differently — Bijoy and Bijay, Subhadip and Subhadeep, Hritick and Hritik —
    so an exact match would call one man two people and fill the report with
    disputes that are not disputes. But a *shared surname* is not a shared
    identity, and that is the harder half: Somnath Sardar and Milon Sardar
    score 0.81 as whole strings, and they are two different men sharing one
    person record, which is the case this whole reconciliation exists to catch.
    So every token on the shorter side must find its own partner on the other.
    A common surname alone can then never carry a match.

    Pairing rather than position, because names arrive surname-first about as
    often as not, and a middle name appears on one side and not the other.

    0.75 per token was measured against this fleet's first names. One man:
    bijoy/bijay 0.80, subhadip/subhadeep 0.82, hritick/hritik and
    subham/shubham 0.92. Two men: somnath/milon 0.33, pradip/nasiruddin 0.38,
    tapash/baby 0.20, jeet/anand 0.00. The gap is wide and the line sits in the
    middle of it.
    """
    ta, tb = _norm(a).split(), _norm(b).split()
    if not ta or not tb:
        return False
    if ta == tb:
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


def _days(amount: int, full_week: int | None) -> int:
    """How many days the provider billed, from their own amount.

    Their full week divided by seven is their daily rate; the amount divided by
    that is the days. Rounded, because a provider's daily figure is itself
    rounded and 3 x 175 = 525 has to come back as 3 and not 2.99.
    """
    if not full_week or amount <= 0:
        return 0
    return max(1, min(7, round(amount * 7 / full_week)))


def full_week_rates(lines: list[dict]) -> dict[str, int]:
    """The provider's full-week amount per model, read off the bill itself.

    The largest non-damage amount charged for a model in a given week *is* the
    full week — every other line on that model is a fraction of it. Taking it
    from the bill rather than a stored rate card means a provider's price rise
    needs no code change and cannot silently skew a whole week's Expected.
    """
    top: dict[str, int] = {}
    for ln in lines:
        if ln.get("is_damage"):
            continue
        m = ln.get("model") or ""
        amt = int(ln.get("amount") or 0)
        if amt > top.get(m, 0):
            top[m] = amt
    return top


def _window(period_start: str, period_end: str) -> set[str]:
    """Cycle end dates that belong to this billing week.

    Companies close on different days, so one provider week faces three or four
    of our cycles. A ledger row counts if its cycle ended inside the window.
    """
    try:
        a, b = date.fromisoformat(period_start), date.fromisoformat(period_end)
    except ValueError:
        return set()
    return {(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)}


def _load(conn, period_start: str, period_end: str) -> dict[str, Any]:
    """Everything the reconciler needs, in four queries rather than per line."""
    units = {
        r["ev_id"]: dict(r)
        for r in conn.execute(
            "SELECT u.ev_id, u.status, m.provider, m.model_name AS model, m.weekly_rate, "
            "       a.person_id, a.handover_date, a.returned_date, "
            "       pr.display_name AS holder, "
            "       (SELECT MAX(x.returned_date) FROM ev_assignments x WHERE x.ev_id=u.ev_id) "
            "         AS last_return "
            "FROM ev_units u "
            "JOIN ev_models m ON m.model_id = u.model_id "
            "LEFT JOIN ev_assignments a ON a.ev_id = u.ev_id AND a.returned_date IS NULL "
            "LEFT JOIN person_registry pr ON pr.person_id = a.person_id "
        )
    }
    # Every assignment that touched the window, so a unit handed on mid-week
    # still names whoever actually had it.
    legs = defaultdict(list)
    for r in conn.execute(
        "SELECT a.ev_id, a.person_id, a.handover_date, a.returned_date, "
        "       pr.display_name AS holder "
        "FROM ev_assignments a "
        "LEFT JOIN person_registry pr ON pr.person_id = a.person_id "
        "WHERE (a.returned_date IS NULL OR a.returned_date >= ?) "
        "  AND (a.handover_date IS NULL OR a.handover_date <= ?) "
        "ORDER BY a.handover_date",
        (period_start, period_end),
    ):
        legs[r["ev_id"]].append(dict(r))

    # The rent ledger. A single-day cycle is a hand-booked entry — somebody
    # settled it outside any payout — and has to be kept apart or it reads as
    # part of the week's normal recovery.
    ends = _window(period_start, period_end)
    ledger: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    manual: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in conn.execute(
        "SELECT person_id, event_type, amount, cycle_start, cycle_end, created_by "
        "FROM transactions WHERE event_type IN "
        "  ('RENT','RENT_COLLECTED','RENT_MISSED','RENT_RECOVERED','RENT_REVERSAL')"
    ):
        pid, amt = int(r["person_id"]), abs(int(r["amount"] or 0))
        single = r["cycle_start"] == r["cycle_end"]
        if single and "migration" not in (r["created_by"] or ""):
            manual[pid][r["event_type"]] += amt
        elif not single and r["cycle_end"] in ends:
            ledger[pid][r["event_type"]] += amt

    # Who holds what now, by name, for chasing a renamed id.
    holders = [
        dict(r)
        for r in conn.execute(
            "SELECT a.person_id, a.ev_id, pr.display_name AS holder "
            "FROM ev_assignments a "
            "JOIN person_registry pr ON pr.person_id = a.person_id "
            "WHERE a.returned_date IS NULL"
        )
    ]
    # The name each company registered a person under. A company registers
    # whoever turned up at their desk, so one person_id can carry two names —
    # and a provider billing "MILON SARDAR" may be naming the second of them.
    id_names = defaultdict(set)
    for r in conn.execute(
        "SELECT person_id, name FROM rider_master WHERE name IS NOT NULL AND name <> ''"
    ):
        id_names[int(r["person_id"])].add(r["name"])
    return {
        "units": units,
        "legs": legs,
        "ledger": ledger,
        "manual": manual,
        "holders": holders,
        "id_names": id_names,
    }


def _model_guess(ev_id: str) -> str:
    """A model for a unit the DB has never seen, from the provider's own id
    shape. Only used for Expected on a line we cannot otherwise price."""
    return "Blue" if ev_id.upper().startswith("CBICEVD") else "Regular"


def reconcile(
    conn,
    lines: list[dict],
    period_start: str,
    period_end: str,
    overrides: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Turn parsed bill lines into the week's report.

    ``lines`` carry ``ev_id``, ``amount`` (paise), and optionally ``vin``,
    ``provider_name``, ``remark``, ``deploy_date``, ``line_no``. ``overrides``
    is ``{ev_id: {field: value}}`` and is applied last, after everything
    derived, so a correction always wins.

    Returns ``{"rows": [...], "totals": {...}, "tag_counts": {...}}``, all
    money in paise for the API boundary to rupeeize.
    """
    ov = overrides or {}
    data = _load(conn, period_start, period_end)
    units, legs = data["units"], data["legs"]
    ledger, manual = data["ledger"], data["manual"]

    # ── first pass: what each line is about, and what it should have cost ────
    prepared: list[dict] = []
    for ln in lines:
        ev = str(ln.get("ev_id") or "").strip()
        amount = int(ln.get("amount") or 0)
        remark = (ln.get("remark") or "").upper()
        u = units.get(ev) or units.get(ev.upper())
        prepared.append(
            {
                **ln,
                "ev_id": ev,
                "amount": amount,
                "is_damage": "DAMAGE" in remark,
                "returned_remark": "RETURN DT" in remark,
                "model": (u or {}).get("model") or _model_guess(ev),
                "unit": u,
            }
        )
    full = full_week_rates(prepared)

    # ── who each line belongs to, and how many units that person was billed ──
    for p in prepared:
        u, ev, name = p["unit"], p["ev_id"], p.get("provider_name")
        pid = holder = None
        renamed = swapped = None
        if u and u.get("person_id"):
            pid, holder = int(u["person_id"]), u.get("holder")
        elif u:
            # No open assignment. Did anybody hold it during the week?
            leg = next((x for x in legs.get(ev, []) if x.get("person_id")), None)
            if leg:
                pid, holder = int(leg["person_id"]), leg.get("holder")
        if pid is None:
            # Follow the rider instead of the id: a provider often keeps
            # billing an id we have since renamed, and the vehicle is really on
            # the rider's current unit.
            alt = next(
                (
                    h
                    for h in data["holders"]
                    if same_person(h["holder"], name)
                    or any(same_person(n, name) for n in data["id_names"][int(h["person_id"])])
                ),
                None,
            )
            if alt:
                pid, holder = int(alt["person_id"]), alt["holder"]
                if u is None:
                    renamed = alt["ev_id"]
                else:
                    swapped = alt["ev_id"]
        p["person_id"] = pid
        p["holder"] = holder
        p["renamed_to"] = renamed
        p["swapped_to"] = swapped
        p["days"] = 0 if p["is_damage"] else _days(p["amount"], full.get(p["model"]))
        rate = int((u or {}).get("weekly_rate") or 0)
        p["expected"] = 0 if p["is_damage"] else round(rate * p["days"] / 7)

    # A person billed for more than one unit has one ledger figure covering all
    # of them. Split it by what each unit should have cost, or the bigger
    # vehicle swallows the whole payment and the smaller reads as unpaid.
    per_person = defaultdict(list)
    for p in prepared:
        if p["person_id"] and not p["is_damage"]:
            per_person[p["person_id"]].append(p)

    rows: list[dict] = []
    for p in prepared:
        pid = p["person_id"]
        share = 1.0
        siblings = per_person.get(pid or -1, [])
        if len(siblings) > 1:
            total = sum(x["expected"] for x in siblings) or len(siblings)
            share = (p["expected"] or 1) / total if total else 1 / len(siblings)
        led = ledger.get(pid or -1, {})
        man = manual.get(pid or -1, {})

        def cut(v: float, share: float = share) -> int:
            """This person's ledger figure, as far as this one unit goes."""
            return round(v * share)

        charged = cut(led.get("RENT", 0) + led.get("RENT_MISSED", 0))
        collected = cut(led.get("RENT_COLLECTED", 0) + led.get("RENT_RECOVERED", 0))
        missed = max(0, cut(led.get("RENT_MISSED", 0)) - cut(led.get("RENT_RECOVERED", 0)))
        by_hand = min(missed, cut(man.get("RENT_RECOVERED", 0)))
        missed -= by_hand
        collected += by_hand
        reversed_off = min(missed, cut(man.get("RENT_REVERSAL", 0)))
        missed -= reversed_off

        u = p["unit"]
        held = bool(u and u.get("person_id"))
        rows.append(
            {
                "line_no": p.get("line_no"),
                "ev_id": p["ev_id"],
                "vin": p.get("vin"),
                "provider_name": p.get("provider_name"),
                "deploy_date": p.get("deploy_date"),
                "remark": p.get("remark"),
                "person_id": pid,
                "rider": p["holder"] or p.get("provider_name"),
                "days": p["days"],
                "billed": p["amount"],
                "expected": p["expected"] or None,
                "charged": charged or None,
                "collected": collected or None,
                "missed": missed or None,
                "hand_booked": cut(man.get("RENT_RECOVERED", 0)) or None,
                "damage": p["amount"] if p["is_damage"] else None,
                "unit_status": (u or {}).get("status") or "not in DB",
                "held": held,
                "renamed_to": p["renamed_to"],
                "swapped_to": p["swapped_to"],
                "reversed": reversed_off or None,
                "by_hand": by_hand or None,
            }
        )
        rows[-1]["tag"], rows[-1]["note"] = _tag_and_note(rows[-1], p)

    # ── the office's corrections, last, so they always win ──────────────────
    for r in rows:
        for field, value in (ov.get(r["ev_id"]) or {}).items():
            if field not in OVERRIDE_FIELDS:
                continue
            if field in ("expected", "charged", "collected"):
                try:
                    r[field] = int(round(float(value) * 100))
                except (TypeError, ValueError):
                    continue
            elif field == "person_id":
                try:
                    r["person_id"] = int(value)
                except (TypeError, ValueError):
                    continue
            elif field == "note":
                r["note"] = value
            elif field == "tag" and value in TAGS:
                r["tag"] = value
            elif field == "rider":
                r["rider"] = value
            r["overridden"] = sorted(set(r.get("overridden") or []) | {field})

    totals = {
        "lines": len(rows),
        "billed": sum(r["billed"] for r in rows),
        "damage": sum(r["damage"] or 0 for r in rows),
        "expected": sum(r["expected"] or 0 for r in rows),
        "charged": sum(r["charged"] or 0 for r in rows),
        "collected": sum(r["collected"] or 0 for r in rows),
        "missed": sum(r["missed"] or 0 for r in rows),
    }
    counts: dict[str, int] = defaultdict(int)
    for r in rows:
        counts[r["tag"]] += 1
    return {"rows": rows, "totals": totals, "tag_counts": dict(counts)}


def _tag_and_note(r: dict, p: dict) -> tuple[str, str]:
    """One tag, and everything the tag no longer carries.

    Precedence is deliberate and runs reason-first: a damage line is not a rent
    question at all, a vehicle that came back is not a collection problem, and
    a charge written off is not a debt. Only when none of those apply does the
    money decide.
    """
    notes: list[str] = []
    if r["renamed_to"]:
        notes.append(f"billed as {r['ev_id']}, the rider is on {r['renamed_to']}")
    if r["swapped_to"]:
        notes.append(f"the rider is on {r['swapped_to']}")
    if p["unit"] is None and not r["renamed_to"]:
        notes.append("not a unit in the DB")
    if r["by_hand"]:
        notes.append("cleared by hand")
    if r["reversed"]:
        notes.append("written off")
    if not r["damage"] and not r["charged"] and not r["collected"] and r["billed"]:
        notes.append("no rider was charged for it")
    if r["provider_name"] and r["rider"] and not same_person(r["provider_name"], r["rider"]):
        notes.append(f"they call him {r['provider_name']}")
    status = (p["unit"] or {}).get("status")
    if status in ("returned", "spare", "maintenance") and not r["held"]:
        last = (p["unit"] or {}).get("last_return")
        word = {"returned": "closed", "spare": "spare", "maintenance": "in the workshop"}[status]
        notes.append(word + (f" {last}" if last and status != "maintenance" else ""))

    note = "; ".join(dict.fromkeys(notes))
    if r["damage"]:
        return "Damage", note
    if r["swapped_to"]:
        return "Swap", note
    if status == "returned" or p["returned_remark"]:
        return "Returned", note
    if r["reversed"] and not r["collected"]:
        return "Reversed", note
    if r["by_hand"] and (r["collected"] or 0) <= (r["by_hand"] or 0):
        return "Paid Manually", note
    collected = r["collected"] or 0
    charged = r["charged"] or 0
    if collected <= 0:
        return "Not collected", note
    if collected < charged - 50:
        return "Partial", note
    if not charged:
        return "Charged", note
    return "Collected", note
