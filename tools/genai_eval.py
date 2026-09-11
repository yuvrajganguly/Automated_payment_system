"""Fifty narrations, graded. Does a local model restate computed money faithfully?

The probe (``genai_probe.py``) answered "can it?" once. This answers "how
often?", which is the only question that decides whether the explainer ships.

Every case is generated against the real schema and priced by the real
``resolve_rent``, so the expected figures are the engine's, not a fixture's.
The model is then handed those figures and asked only to explain them. It is
never asked to compute anything — that question was settled on 2026-09-09,
when it got three different wrong answers to the same sum.

GRADING is deliberately mechanical, because "reads fine to me" is how a wrong
number reaches a rider. A run passes only if:

  * every rupee amount it mentions is one it was given,
  * every "N days" it mentions is one it was given,
  * every date it mentions is one it was given, and
  * the cycle total actually appears.

The third rule is the one that catches the failure seen in testing, where a
narration got every figure right and moved a handover from June to August.
A model that omits detail passes; a model that invents it does not.

    python -m tools.genai_eval                     # 50 cases, temp 0.2
    python -m tools.genai_eval --n 20 --temp 0.8   # compare settings
    python -m tools.genai_eval --model qwen2.5:7b  # compare models

Needs Ollama reachable on localhost:11434 and nothing else. No database, no
network, no server — the cases are built in memory.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

sys.path.insert(0, "src")

from payout.db.schema import apply_schema  # noqa: E402
from payout.domain.rent import resolve_rent  # noqa: E402

OLLAMA = "http://localhost:11434/api/generate"

NARRATE = """\
You are explaining an EV-rental charge to the person who was billed. The
arithmetic below has already been done and verified — treat every number as
given and correct. Do NOT recompute, re-count days, or second-guess the
figures.

Your job is only to explain, in plain English, why the charge is what it is:
what the rider held, over which days, and why any uncharged days were not
charged. Use the figures exactly as written. Do not mention any date or
amount that does not appear below.
"""

# Rates in paise per week, spread so a wrong leg rate shows up as a wrong total.
RATES = [126000, 129500, 118000, 105000, 140000]

WORD_NUM = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
}

MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


# ── case generation ─────────────────────────────────────────────────────────


def _db() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    apply_schema(c)
    return c


def _model(c: sqlite3.Connection, weekly: int) -> int:
    row = c.execute("SELECT model_id FROM ev_models WHERE weekly_rate = ?", (weekly,)).fetchone()
    if row:
        return row["model_id"]
    return c.execute(
        "INSERT INTO ev_models (provider, model_name, weekly_rate) VALUES (?, ?, ?)",
        ("Blive", f"M{weekly}", weekly),
    ).lastrowid


def _person(c: sqlite3.Connection) -> int:
    pid = c.execute("INSERT INTO person_registry (display_name) VALUES ('R')").lastrowid
    c.execute("INSERT OR IGNORE INTO balances (person_id, current_balance) VALUES (?, 0)", (pid,))
    return pid


def _assign(c, pid, ev, weekly, handover, returned=None, meter=None) -> None:
    c.execute(
        "INSERT OR IGNORE INTO ev_units (ev_id, model_id, status) VALUES (?, ?, 'in_use')",
        (ev, _model(c, weekly)),
    )
    c.execute(
        "INSERT INTO ev_assignments (person_id, ev_id, handover_date, returned_date, "
        "rent_charged_through, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (
            pid,
            ev,
            str(handover),
            str(returned) if returned else None,
            str(meter) if meter else None,
            f"{handover} 09:00:00",
        ),
    )


SHAPES = [
    "plain",  # one EV, held throughout
    "swap",  # returned one, took another (the Somnath shape)
    "returned",  # gave it back mid-cycle, no replacement
    "new_rider",  # first handover lands inside the cycle
    "maintenance",  # workshop days inside the cycle
    "maint_edge",  # maintenance straddling the cycle boundary
    "catchup",  # meter sits behind the cycle
    "two_rates",  # swap between EVs on different rate cards
    "short_cycle",  # a 3-4 day cycle
    "nothing",  # returned before the cycle: no chargeable days
]


def make_case(rng: random.Random, shape: str):
    """Build one priced case. Returns (conn, person_id, cycle_start, cycle_end)."""
    c = _db()
    pid = _person(c)
    start = date(2026, rng.randint(1, 11), rng.randint(1, 20))
    length = rng.choice([3, 4]) if shape == "short_cycle" else rng.choice([7, 7, 7, 10, 14])
    cs, ce = start, start + timedelta(days=length - 1)
    meter = cs - timedelta(days=1)
    w1, w2 = rng.choice(RATES), rng.choice(RATES)

    if shape == "two_rates":
        while w2 == w1:
            w2 = rng.choice(RATES)

    if shape in ("plain", "catchup", "short_cycle"):
        m = meter - timedelta(days=rng.randint(3, 6)) if shape == "catchup" else meter
        _assign(c, pid, "EVA", w1, cs - timedelta(days=90), meter=m)
    elif shape in ("swap", "two_rates"):
        cut = cs + timedelta(days=rng.randint(1, max(1, length - 3)))
        _assign(c, pid, "EVA", w1, cs - timedelta(days=60), returned=cut, meter=meter)
        _assign(c, pid, "EVB", w2, cut)
    elif shape == "returned":
        cut = cs + timedelta(days=rng.randint(2, max(2, length - 2)))
        _assign(c, pid, "EVA", w1, cs - timedelta(days=45), returned=cut, meter=meter)
    elif shape == "new_rider":
        _assign(c, pid, "EVA", w1, cs + timedelta(days=rng.randint(1, max(1, length - 3))))
    elif shape in ("maintenance", "maint_edge"):
        _assign(c, pid, "EVA", w1, cs - timedelta(days=30), meter=meter)
        if shape == "maintenance":
            f = cs + timedelta(days=rng.randint(1, max(1, length - 3)))
            t = f + timedelta(days=rng.randint(0, 2))
        else:
            f, t = cs - timedelta(days=2), cs + timedelta(days=1)
        c.execute(
            "INSERT INTO ev_maintenance (ev_id, from_date, to_date) VALUES ('EVA', ?, ?)",
            (str(f), str(t)),
        )
    elif shape == "nothing":
        _assign(
            c,
            pid,
            "EVA",
            w1,
            cs - timedelta(days=60),
            returned=cs - timedelta(days=5),
            meter=cs - timedelta(days=6),
        )

    c.commit()
    return c, pid, cs, ce


# ── prompt ──────────────────────────────────────────────────────────────────


def _r(paise) -> str:
    return f"Rs {paise / 100:,.2f}"


def build_prompt(info, cs: date, ce: date) -> tuple[str, dict]:
    """The narration prompt, plus the set of facts the model is allowed to use."""
    money, days, dates = set(), set(), {cs, ce}
    lines = [NARRATE, "", "=== ALREADY COMPUTED ===", "", f"Cycle: {cs} to {ce}"]

    if not info.legs or info.days == 0:
        lines.append("  No chargeable days in this cycle.")
    for i, leg in enumerate(info.legs, 1):
        daily = round(leg.weekly_rate / 7)
        money |= {int(leg.rent), daily, int(leg.weekly_rate)}
        days.add(leg.days)
        if leg.rent_from:
            dates.add(leg.rent_from)
        if leg.rent_through:
            dates.add(leg.rent_through)
        lines.append(
            f"  EV-{i}: charged {leg.days} days ({leg.rent_from} to {leg.rent_through}) "
            f"at {_r(daily)}/day = {_r(int(leg.rent))}"
        )
        if leg.returned_date:
            dates.add(leg.returned_date)
            lines.append(f"     returned {leg.returned_date} (return day not charged)")
        if leg.maintenance_days:
            days.add(leg.maintenance_days)
            lines.append(f"     {leg.maintenance_days} day(s) in the workshop, not charged")

    money.add(int(info.rent))
    days.add(info.days)
    lines += [
        "",
        f"TOTAL CHARGED: {info.days} days = {_r(int(info.rent))}",
        "",
        "=== QUESTION ===",
        "",
        "Explain this charge to the rider.",
    ]
    return "\n".join(lines), {
        "money": money,
        "days": days,
        "dates": dates,
        # Explicit: the largest allowed amount is often a weekly rate card,
        # not the cycle total, so max() picks the wrong number.
        "total": int(info.rent),
    }


# ── grading ─────────────────────────────────────────────────────────────────

# "Rs" is a prefix in Indian usage; allowing it as a suffix too made "EV-2, Rs
# 1,120" parse as the amount "2," and swallow the real figure behind it.
_MONEY = re.compile(r"(?:rs\.?|inr|₹)\s*([\d,]+(?:\.\d+)?)|([\d,]+(?:\.\d+)?)\s*rupees", re.I)
_DAYS = re.compile(r"\b([\d,]+|" + "|".join(WORD_NUM) + r")\s+days?\b", re.I)
_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_LONG = re.compile(
    r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?\b"
    r"|\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + "|".join(MONTHS) + r")\b",
    re.I,
)


def _paise(tok: str) -> int:
    return round(float(tok.replace(",", "")) * 100)


def grade(reply: str, allowed: dict) -> list[str]:
    """Return a list of problems. Empty list = pass."""
    bad: list[str] = []

    for m in _MONEY.finditer(reply):
        tok = m.group(1) or m.group(2)
        if _paise(tok) not in allowed["money"]:
            bad.append(f"money {tok}")

    for m in _DAYS.finditer(reply):
        tok = m.group(1).lower()
        n = WORD_NUM.get(tok)
        if n is None:
            try:
                n = int(tok.replace(",", ""))
            except ValueError:
                continue
        if n not in allowed["days"]:
            bad.append(f"days {tok}")

    seen_md = {(d.month, d.day) for d in allowed["dates"]}
    for m in _ISO.finditer(reply):
        y, mo, dd = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if date(y, mo, dd) not in allowed["dates"]:
            bad.append(f"date {m.group(0)}")
    for m in _LONG.finditer(reply):
        mon = (m.group(1) or m.group(4)).lower()
        day = int(m.group(2) or m.group(3))
        if (MONTHS[mon], day) not in seen_md:
            bad.append(f"date {m.group(0)}")

    total = allowed["total"]
    if not any(_paise(m.group(1) or m.group(2)) == total for m in _MONEY.finditer(reply)):
        bad.append("total missing")
    return bad


# ── runner ──────────────────────────────────────────────────────────────────


def ask(model: str, prompt: str, temp: float, timeout: int) -> str:
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temp, "num_predict": 300},
        }
    ).encode()
    req = urllib.request.Request(OLLAMA, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["response"]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=50)
    ap.add_argument("--model", default="llama3.1:8b")
    ap.add_argument("--temp", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=7, help="same seed = same 50 cases")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--log", default="eval_failures.txt")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    passed, failures = 0, []

    print(f"{args.n} cases · {args.model} · temperature {args.temp}\n")
    for i in range(1, args.n + 1):
        shape = SHAPES[(i - 1) % len(SHAPES)]
        conn, pid, cs, ce = make_case(rng, shape)
        try:
            info = resolve_rent(conn, pid, cs, ce)
            prompt, allowed = build_prompt(info, cs, ce)
        finally:
            conn.close()

        try:
            reply = ask(args.model, prompt, args.temp, args.timeout)
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"\n  Ollama unreachable ({e}). Is it running?")
            return 2

        bad = grade(reply, allowed)
        if bad:
            failures.append((i, shape, bad, prompt, reply))
            print(f"{i:3}. {shape:<12} FAIL  {', '.join(bad[:3])}")
        else:
            passed += 1
            print(f"{i:3}. {shape:<12} ok")

    print(f"\n{passed}/{args.n} passed ({100 * passed / args.n:.0f}%)")
    if failures:
        with open(args.log, "w", encoding="utf-8") as fh:
            for i, shape, bad, prompt, reply in failures:
                fh.write(f"{'=' * 70}\nCASE {i} ({shape}) — {', '.join(bad)}\n{'=' * 70}\n")
                fh.write(f"{prompt}\n\n--- MODEL SAID ---\n{reply}\n\n")
        print(f"failures written to {args.log}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
