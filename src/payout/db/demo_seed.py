"""Demo fleet seed — a realistic, fully-populated dataset for the live demo.

Generates a believable multi-company gig fleet anchored to the most recent
complete Mon-Sun weeks, so the dashboard's default window (the previous week)
is never empty. It writes the same shapes the real engine does — payouts, EV
rent billed / missed / recovered, a day-level ``ev_daily_ledger``, per-company
cycle rollups, arrears and COD holds — using entirely fictional names.

Guarded by ``_already_seeded``: if the database already has people (i.e. the
operator's real data), this does nothing.
"""

from __future__ import annotations

import random
import sqlite3
from datetime import date, timedelta

COMPANIES = ["Dealshare", "Myntra", "Jiffy", "Zepto", "Blitz"]
# Rough relative size of each company's rider base.
CO_WEIGHT = {"Dealshare": 8, "Myntra": 16, "Jiffy": 9, "Zepto": 6, "Blitz": 11}
MODELS = [
    ("Raft", "Regular", 125000),
    ("Raft", "Blue", 129500),
    ("Blive", "Standard", 126000),
]  # paise
HUBS = [
    "Behala",
    "Dum Dum",
    "New Alipore",
    "Kasba",
    "Nagar Bazar",
    "Kalyani",
    "Maheshtala",
    "Rajpur",
    "New Town",
    "Salt Lake",
    "Garia",
    "Howrah",
    "Barasat",
    "Sonarpur",
]
FIRST = [
    "Subhankar",
    "Rahul",
    "Amit",
    "Sourav",
    "Akash",
    "Rohit",
    "Bikash",
    "Suman",
    "Tarak",
    "Prakash",
    "Debashis",
    "Arjun",
    "Manoj",
    "Sanjay",
    "Raju",
    "Imran",
    "Sahil",
    "Deepak",
    "Niloy",
    "Pintu",
    "Gopal",
    "Habib",
    "Kunal",
    "Sourabh",
    "Tanmoy",
    "Biplab",
    "Ranjan",
    "Asif",
]
LAST = [
    "Das",
    "Ghosh",
    "Singh",
    "Mondal",
    "Roy",
    "Sardar",
    "Mistry",
    "Pal",
    "Naskar",
    "Halder",
    "Dutta",
    "Barui",
    "Sadhukhan",
    "Mahato",
    "Khan",
    "Yadav",
    "Bose",
    "Sett",
    "Pramanik",
    "Hembram",
]

N_PERSONS = 48
EV_SHARE = 0.72  # fraction of riders who hold an EV
SECOND_CO_SHARE = 0.18  # fraction who also work a second company


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _recent_weeks(today: date, n: int = 3):
    """Last ``n`` complete Mon-Sun weeks; newest last = the default window."""
    this_mon = _monday(today)
    return [
        (this_mon - timedelta(days=7 * k), this_mon - timedelta(days=7 * k - 6))
        for k in range(n, 0, -1)
    ]


def _week_bucket(cycle_end: str) -> str:
    d = date.fromisoformat(cycle_end)
    return f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"


def _already_seeded(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT COUNT(*) FROM person_registry").fetchone()[0] > 0


def seed_demo(conn: sqlite3.Connection) -> None:
    if _already_seeded(conn):
        return
    rng = random.Random(7)
    today = date.today()
    weeks = _recent_weeks(today, 3)  # [w1, w2, w3]; w3 = previous week
    newest = weeks[-1]
    ds = lambda d: d.isoformat()  # noqa: E731

    # ── Companies, rate card, EV units ──────────────────────────────────────
    for c in COMPANIES:
        conn.execute(
            "INSERT OR IGNORE INTO companies (company_name, parser_type, "
            "rider_id_column, payout_column, is_active) VALUES (?,?,?,?,1)",
            (c, c.lower(), "rider_id", "payout"),
        )
    model_id = {}
    for prov, name, rate in MODELS:
        conn.execute(
            "INSERT OR IGNORE INTO ev_models (provider, model_name, weekly_rate) VALUES (?,?,?)",
            (prov, name, rate),
        )
        model_id[(prov, name)] = conn.execute(
            "SELECT model_id FROM ev_models WHERE provider=? AND model_name=?", (prov, name)
        ).fetchone()[0]

    evs = []  # (ev_id, weekly_rate)
    for i in range(1, 41):
        prov, name, rate = MODELS[rng.randrange(len(MODELS))]
        ev_id = f"{'RAFT' if prov == 'Raft' else 'BLV'}{1400 + i}"
        conn.execute(
            "INSERT OR IGNORE INTO ev_units (ev_id, model_id, status) VALUES (?,?, 'in_use')",
            (ev_id, model_id[(prov, name)]),
        )
        evs.append((ev_id, rate))
    rng.shuffle(evs)
    ev_pool = list(evs)

    weighted_cos = [c for c in COMPANIES for _ in range(CO_WEIGHT[c])]

    # ── People ──────────────────────────────────────────────────────────────
    persons = []
    for i in range(N_PERSONS):
        name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        pid = conn.execute(
            "INSERT INTO person_registry (display_name) VALUES (?)", (name,)
        ).lastrowid
        primary = rng.choice(weighted_cos)
        cos = [primary]
        if rng.random() < SECOND_CO_SHARE:
            alt = rng.choice([c for c in COMPANIES if c != primary])
            cos.append(alt)
        hub = rng.choice(HUBS)
        for ci, co in enumerate(cos):
            rid = f"{co[:2].upper()}{1000 + i}{ci}"
            conn.execute(
                "INSERT INTO rider_master (rider_id, company, person_id, name, hub, "
                "vehicle, account_no, ifsc, is_active) VALUES (?,?,?,?,?,?,?,?,1)",
                (
                    rid,
                    co,
                    pid,
                    name,
                    hub,
                    "EV",
                    f"9{rng.randint(10**9, 10**10 - 1)}",
                    "HDFC0001234",
                ),
            )
        has_ev = rng.random() < EV_SHARE and ev_pool
        ev = ev_pool.pop() if has_ev else None
        if ev:
            conn.execute(
                "INSERT INTO ev_assignments (person_id, ev_id, handover_date, "
                "rent_charged_through) VALUES (?,?,?,?)",
                (pid, ev[0], ds(weeks[0][0] - timedelta(days=rng.randint(7, 40))), None),
            )
            conn.execute(
                "UPDATE person_registry SET deduction_company=?, deduction_rider_id=? "
                "WHERE person_id=?",
                (primary, f"{primary[:2].upper()}{1000 + i}0", pid),
            )
        persons.append(
            {
                "pid": pid,
                "name": name,
                "primary": primary,
                "cos": cos,
                "hub": hub,
                "rid": f"{primary[:2].upper()}{1000 + i}0",
                "ev": ev,
                "reliability": rng.uniform(0.80, 0.99),
            }
        )

    # ── Cycles: payouts + rent + day ledger + rollups ───────────────────────
    cyc = {}  # (company, w) -> aggregate dict
    arrears = {}  # pid -> {missed, recovered}
    missed_days = {}  # pid -> list of (ev_id, day, cost) still missed

    def agg(co, w):
        k = (co, w)
        cyc.setdefault(
            k,
            dict(
                rider_count=0,
                riders_paid=0,
                riders_in_dues=0,
                total_release=0.0,
                total_rent_charged=0.0,
                total_rent_collected=0.0,
                total_rent_missed=0.0,
            ),
        )
        return cyc[k]

    def txn(pid, rid, co, w, etype, amount, *, days=None, remarks="", by="engine"):
        return conn.execute(
            "INSERT INTO transactions (person_id, rider_id, company, cycle_start, "
            "cycle_end, event_type, amount, balance_after, days, remarks, created_by, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                pid,
                rid,
                co,
                ds(w[0]),
                ds(w[1]),
                etype,
                amount,
                0.0,
                days,
                remarks,
                by,
                f"{ds(w[1])} 12:00:00",
            ),
        ).lastrowid

    def ledger(ev_id, w, pid, rate, status, event_id):
        from payout.money import split_evenly

        days = []
        d = w[0]
        while d <= w[1]:
            days.append(d)
            d += timedelta(days=1)
        prov = round(rate / 7)
        parts = split_evenly(rate, len(days))  # rider cost sums to the week's rate
        for i, dd in enumerate(days):
            conn.execute(
                "INSERT INTO ev_daily_ledger (ev_id, day, state, "
                "assigned_person_id, daily_cost, provider_cost, billing_status, "
                "cycle_event_id) VALUES (?,?, 'billable',?,?,?,?,?) "
                "ON CONFLICT(ev_id, day) DO UPDATE SET state=excluded.state, "
                "assigned_person_id=excluded.assigned_person_id, "
                "daily_cost=excluded.daily_cost, provider_cost=excluded.provider_cost, "
                "billing_status=excluded.billing_status, "
                "cycle_event_id=excluded.cycle_event_id",
                (ev_id, ds(dd), pid, parts[i], prov, status, event_id),
            )

    for wi, w in enumerate(weeks):
        for p in persons:
            co = p["primary"]
            a = agg(co, w)
            # Absences cluster in the newest week so we get visible inactives.
            present = rng.random() < (p["reliability"] - (0.10 if wi == len(weeks) - 1 else 0.0))
            ev = p["ev"]
            rate = ev[1] if ev else 0.0
            daily = round(rate / 7)  # paise
            if present:
                a["rider_count"] += 1
                a["riders_paid"] += 1
                payout = rng.randint(14, 90) * 10000  # paise (1400..9000 rupees)
                txn(p["pid"], p["rid"], co, w, "PAYOUT", payout, remarks="weekly payout")
                if ev:
                    rid_txn = txn(
                        p["pid"], p["rid"], co, w, "RENT", -rate, days=7, remarks="EV rent"
                    )
                    ledger(ev[0], w, p["pid"], rate, "billed", rid_txn)
                    txn(
                        p["pid"],
                        p["rid"],
                        co,
                        w,
                        "RENT_COLLECTED",
                        rate,
                        remarks="rent collected from payout",
                    )
                    a["total_rent_charged"] += rate
                    a["total_rent_collected"] += rate
                    release = max(0, payout - rate)
                else:
                    release = payout
                txn(p["pid"], p["rid"], co, w, "RELEASE", -release, remarks="net released")
                a["total_release"] += release
            elif ev:
                # Absent EV holder -> rent missed -> arrears, missed day-rows.
                mid = txn(
                    p["pid"],
                    p["rid"],
                    co,
                    w,
                    "RENT_MISSED",
                    -rate,
                    days=7,
                    remarks="absent from payout",
                )
                ledger(ev[0], w, p["pid"], rate, "missed", mid)
                ar = arrears.setdefault(p["pid"], {"missed": 0.0, "recovered": 0.0})
                ar["missed"] += rate
                md = missed_days.setdefault(p["pid"], [])
                d = w[0]
                while d <= w[1]:
                    md.append((ev[0], ds(d)))
                    d += timedelta(days=1)
                a["rider_count"] += 1
                a["riders_in_dues"] += 1
                a["total_rent_missed"] += rate

    # ── Recoveries: a few riders clear old arrears, dated in the newest week ─
    candidates = [p for p in persons if p["pid"] in arrears and p["ev"]]
    rng.shuffle(candidates)
    for p in candidates[:6]:
        ar = arrears[p["pid"]]
        out = ar["missed"] - ar["recovered"]
        if out <= 0:
            continue
        pay = min(out, p["ev"][1])  # claw back ~one week (paise)
        rev = txn(
            p["pid"],
            p["rid"],
            p["primary"],
            newest,
            "RENT_RECOVERED",
            pay,
            remarks="arrears cleared (manual)",
            by="demo",
        )
        # Flip that many missed day-rows to 'recovered'.
        daily = round(p["ev"][1] / 7.0, 2)
        budget = pay
        for ev_id, day in list(missed_days.get(p["pid"], [])):
            if budget + 0.01 < daily:
                break
            conn.execute(
                "UPDATE ev_daily_ledger SET billing_status='recovered', recovery_event_id=? "
                "WHERE ev_id=? AND day=?",
                (rev, ev_id, day),
            )
            budget -= daily
            missed_days[p["pid"]].remove((ev_id, day))
        ar["recovered"] += pay

    # ── Arrears table ───────────────────────────────────────────────────────
    for pid, ar in arrears.items():
        out = ar["missed"] - ar["recovered"]
        conn.execute(
            "INSERT INTO ev_arrears (person_id, total_missed, "
            "total_recovered, outstanding, last_updated) VALUES (?,?,?,?, date('now')) "
            "ON CONFLICT(person_id) DO UPDATE SET total_missed=excluded.total_missed, "
            "total_recovered=excluded.total_recovered, outstanding=excluded.outstanding, "
            "last_updated=excluded.last_updated",
            (pid, ar["missed"], ar["recovered"], out),
        )

    # ── COD holds (newest week) ─────────────────────────────────────────────
    cod_persons = rng.sample(persons, 16)
    for p in cod_persons:
        src = "jiffy_sheet" if p["primary"] == "Jiffy" else "myntra_column"
        conn.execute(
            "INSERT INTO cod_holds (cycle_start, cycle_end, company, rider_id, "
            "person_id, worker_code, order_number, amount, payment_mode, txn_status, "
            "source, created_at) VALUES (?,?,?,?,?,?,?,?, 'COD', 'pending', ?, ?)",
            (
                ds(newest[0]),
                ds(newest[1]),
                p["primary"],
                p["rid"],
                p["pid"],
                p["rid"],
                f"ORD{rng.randint(100000, 999999)}",
                rng.randint(2, 18) * 10000,  # paise
                src,
                f"{ds(newest[1])} 12:00:00",
            ),
        )

    # ── company_cycles rollups ──────────────────────────────────────────────
    for (co, w), a in cyc.items():
        conn.execute(
            "INSERT OR IGNORE INTO company_cycles (company, cycle_start, cycle_end, "
            "week_bucket, processed_by, rider_count, riders_paid, riders_in_dues, "
            "total_release, total_rent_charged, total_rent_collected, total_rent_missed) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                co,
                ds(w[0]),
                ds(w[1]),
                _week_bucket(ds(w[1])),
                "demo",
                a["rider_count"],
                a["riders_paid"],
                a["riders_in_dues"],
                a["total_release"],
                a["total_rent_charged"],
                a["total_rent_collected"],
                a["total_rent_missed"],
            ),
        )

    # ── balances + status ───────────────────────────────────────────────────
    present_newest = {
        r["person_id"]
        for r in conn.execute(
            "SELECT DISTINCT person_id FROM transactions WHERE event_type='PAYOUT' AND cycle_end=?",
            (ds(newest[1]),),
        )
    }
    for p in persons:
        out = arrears.get(p["pid"], {})
        bal = (
            -round(out.get("missed", 0.0) - out.get("recovered", 0.0), 2)
            if p["pid"] in arrears
            else 0.0
        )
        conn.execute(
            "INSERT INTO balances (person_id, current_balance, last_updated) "
            "VALUES (?,?, datetime('now')) "
            "ON CONFLICT(person_id) DO UPDATE SET "
            "current_balance=excluded.current_balance, last_updated=excluded.last_updated",
            (p["pid"], 0.0),
        )
        active = p["pid"] in present_newest
        conn.execute(
            "INSERT INTO status_tracking (person_id, status, last_seen) "
            "VALUES (?,?,?) "
            "ON CONFLICT(person_id) DO UPDATE SET status=excluded.status, "
            "last_seen=excluded.last_seen",
            (p["pid"], "active" if active else "inactive", ds(newest[1])),
        )
        _ = bal

    conn.commit()
    print(
        f"[demo_seed] Seeded demo fleet: {len(persons)} riders across "
        f"{len(COMPANIES)} companies, weeks {ds(weeks[0][0])}..{ds(newest[1])}."
    )
