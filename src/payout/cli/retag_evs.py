"""Move a vehicle onto the model its ID says it belongs to.

Eight units reached the fleet in September 2026 recorded as Blive Standard
with ``CBICEVD`` IDs. ``CBICEVD`` is the Raft Blue pattern; Blive IDs begin
``KOL``. Nothing was corrupt — the vehicles are real and the riders are real —
but the rate card follows the model, so each of them had been billing 1,260 a
week instead of 1,295 since the day it was added.

Run it inside the app container::

    docker exec -i payout python - < retag_evs.py            # dry run
    docker exec -i payout python - --apply < retag_evs.py    # commit

Nothing is hard-coded. It reads ``ev_models.id_prefix`` and reports any unit
whose ID matches one model's pattern while sitting on another — so it finds
the eight, and it will find the next one too.

**History is not rewritten.** ``transactions`` is append-only and
``ev_daily_ledger`` keeps the ``daily_cost`` it was written with, so every
rupee already charged stays exactly as charged. What changes is the rate used
from here on, and for any day not yet billed. The shortfall already booked is
printed rather than corrected, because collecting it back from riders is a
decision for the office, not for a script.
"""

from __future__ import annotations

import sys

from payout.db import get_connection


def _rupees(paise: float) -> str:
    return f"{int(round(paise)) / 100:,.0f}"


def find_mismatches(conn) -> list[dict]:
    """Units sitting on one model while their ID matches another's pattern."""
    prefixes = [
        (
            r["model_id"],
            (r["id_prefix"] or "").upper(),
            r["provider"],
            r["model_name"],
            r["weekly_rate"],
        )
        for r in conn.execute(
            "SELECT model_id, provider, model_name, weekly_rate, id_prefix FROM ev_models "
            "WHERE id_prefix IS NOT NULL AND id_prefix <> ''"
        ).fetchall()
    ]
    # Longest prefix first: if one pattern is a prefix of another, the more
    # specific one has to win or every unit matches the shorter one.
    prefixes.sort(key=lambda p: -len(p[1]))

    out = []
    for r in conn.execute(
        "SELECT u.ev_id, u.status, u.model_id, m.provider, m.model_name, m.weekly_rate, "
        "       m.id_prefix, "
        "       (SELECT p.display_name FROM ev_assignments a "
        "          JOIN person_registry p ON p.person_id = a.person_id "
        "         WHERE a.ev_id = u.ev_id AND a.returned_date IS NULL LIMIT 1) AS holder, "
        "       (SELECT MIN(a.handover_date) FROM ev_assignments a "
        "         WHERE a.ev_id = u.ev_id) AS since "
        "FROM ev_units u JOIN ev_models m ON m.model_id = u.model_id "
        "ORDER BY u.ev_id"
    ).fetchall():
        ev_id = (r["ev_id"] or "").upper()
        match = next((p for p in prefixes if p[1] and ev_id.startswith(p[1])), None)
        if match is None or match[0] == r["model_id"]:
            continue
        mid, _prefix, provider, model_name, rate = match
        # What this unit has actually been billed so far, and what the same
        # days would have come to at the rate it should have been on.
        billed = conn.execute(
            "SELECT COALESCE(SUM(daily_cost), 0) AS charged, COUNT(*) AS days "
            "FROM ev_daily_ledger WHERE ev_id=? AND billing_status IN ('billed', 'missed')",
            (r["ev_id"],),
        ).fetchone()
        days = int(billed["days"] or 0)
        charged = float(billed["charged"] or 0)
        should = days * (int(rate) / 7.0)
        out.append(
            {
                "ev_id": r["ev_id"],
                "status": r["status"],
                "holder": r["holder"],
                "since": r["since"],
                "from": (r["provider"], r["model_name"], int(r["weekly_rate"])),
                "to": (provider, model_name, int(rate)),
                "to_model_id": mid,
                "days": days,
                "charged": charged,
                "should": should,
            }
        )
    return out


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    apply = "--apply" in argv
    say = print
    say("== APPLYING ==" if apply else "== dry run — nothing will change ==")

    with get_connection() as conn:
        rows = find_mismatches(conn)
        if not rows:
            say("\nEvery unit is on the model its ID belongs to. Nothing to do.")
            if not apply:
                conn.rollback()
            return 0

        shortfall = 0.0
        for r in rows:
            fp, fm, fr = r["from"]
            tp, tm, tr = r["to"]
            held = f" — {r['holder']}" if r["holder"] else ""
            since = f", since {r['since']}" if r["since"] else ""
            say(f"\n{r['ev_id']}  [{r['status']}]{held}{since}")
            say(f"   {fp} {fm} ({_rupees(fr)}/wk)  ->  {tp} {tm} ({_rupees(tr)}/wk)")
            if r["days"]:
                gap = r["should"] - r["charged"]
                shortfall += gap
                say(
                    f"   billed {r['days']} day(s) at the old rate: {_rupees(r['charged'])} "
                    f"— the same days at {_rupees(tr)}/wk come to {_rupees(r['should'])} "
                    f"({_rupees(gap)} short)"
                )
            else:
                say("   nothing billed yet, so nothing was undercharged")

        say(f"\n{len(rows)} unit(s). Undercharged so far: {_rupees(shortfall)}.")
        say("That figure is NOT corrected by this script — rent already booked stays booked.")
        say("Recovering it, or letting it go, is the office's call.")

        if not apply:
            conn.rollback()
            say("\n== dry run: nothing changed. Re-run with --apply ==")
            return 0

        for r in rows:
            conn.execute(
                "UPDATE ev_units SET model_id=? WHERE ev_id=?", (r["to_model_id"], r["ev_id"])
            )
            say(f"moved {r['ev_id']} to {r['to'][0]} {r['to'][1]}")
        conn.commit()
        say("\n== committed ==")
        say("Next: Admin → System → EV Models, set Blive's ID pattern to KOL and retire it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
