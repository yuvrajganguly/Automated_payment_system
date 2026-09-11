"""Routes that exist for the recruiter app's first paint.

`GET /app/bootstrap` answers everything the app needs before it can draw a
useful screen — who I am, the companies and hubs for pickers, the size of
the roster and fleet — in one round trip. Nothing here is money.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from payout.api.auth import get_current_user, heads_zone, supervises
from payout.api.ratelimit import rate_limit
from payout.api.routes.hubs import ZONES, fenced_zone
from payout.db import get_connection
from payout.domain.activity import ACTIONS
from payout.domain.naming import display_name_for, name_from
from payout.domain.worked import active_person_sql

router = APIRouter()

APP_API_VERSION = 1  # bump when the app must be updated to keep working


@router.get("/bootstrap")
def bootstrap(user: dict = Depends(get_current_user)) -> dict:
    with get_connection() as conn:
        companies = [
            {
                "company_name": r["company_name"],
                "payment_model": r["payment_model"] or "payout_file",
                "rider_ids_shared_with": r["rider_ids_shared_with"],
            }
            for r in conn.execute(
                "SELECT company_name, payment_model, rider_ids_shared_with FROM companies "
                "WHERE is_active=1 ORDER BY company_name"
            )
        ]
        hub_rows = conn.execute(
            "SELECT h.company, h.hub, ch.zone FROM "
            "(SELECT DISTINCT company, hub FROM rider_master WHERE hub IS NOT NULL AND hub <> '' "
            " UNION SELECT company, hub FROM company_hubs) h "
            "LEFT JOIN company_hubs ch ON ch.company=h.company AND ch.hub=h.hub "
            "WHERE COALESCE(ch.is_active, 1)=1 ORDER BY h.hub, h.company"
        ).fetchall()
        hubs = sorted({r["hub"] for r in hub_rows})
        hub_zones: dict[str, str | None] = {}
        for r in hub_rows:
            hub_zones[r["hub"]] = hub_zones.get(r["hub"]) or r["zone"]
        company_hubs = [
            {"company": r["company"], "hub": r["hub"], "zone": r["zone"]} for r in hub_rows
        ]
        riders_active = conn.execute(
            "SELECT COUNT(*) FROM rider_master WHERE is_active=1"
        ).fetchone()[0]
        persons = conn.execute(
            "SELECT COUNT(DISTINCT person_id) FROM rider_master WHERE is_active=1"
        ).fetchone()[0]
        evs = {
            r["status"]: int(r["n"])
            for r in conn.execute("SELECT status, COUNT(*) AS n FROM ev_units GROUP BY status")
        }
        providers = [
            {"provider": r["provider"], "model_name": r["model_name"], "model_id": r["model_id"]}
            for r in conn.execute(
                "SELECT model_id, provider, model_name FROM ev_models ORDER BY provider, model_name"
            )
        ]
        # What to call this person. The profile's full name if they have filled
        # it in, the display name an admin set otherwise, and only as a last
        # resort the email — which is a login credential, not a name, and
        # reads like one on screen ("YUVRAJ.GANGULY.DS26").
        me_name = display_name_for(conn, user["email"])
    return {
        "api_version": APP_API_VERSION,
        "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "me": {
            "email": user["email"],
            "name": me_name,
            "role": user["role"],
            "phone": user.get("phone"),
            "zone": user.get("zone"),
            # Drives the head's supervision tab. The app must not draw a tab
            # whose route would 403, so this is the flag it checks.
            "is_head": bool(user.get("is_head")),
        },
        "companies": companies,
        "hubs": hubs,
        "hub_zones": hub_zones,
        "company_hubs": company_hubs,
        # Only the zones this caller may actually pick. A fenced recruiter
        # gets one, so the app knows to stop drawing a filter row that offers
        # them a single choice and a synonym for it.
        "zones": [fenced_zone(user).title()] if fenced_zone(user) else list(ZONES),
        "ev_models": providers,
        "counts": {
            "rider_ids_active": int(riders_active),
            "persons_active": int(persons),
            "evs": evs,
        },
    }


# ── Recruiting stats ─────────────────────────────────────────────────────────
# "How many is a recruiter recruiting" — the app's Recruiting tab. A rider id
# counts for the recruiter who created it (rider_master.recruited_by, stamped
# on POST /riders and backfilled from the activity log). Riders are counted by
# rider id (one person with two company ids counts twice, as two onboardings)
# and by person, so both readings are on the screen.


def _period_starts(today: date) -> dict[str, str]:
    return {
        "today": today.isoformat(),
        "week": (today - timedelta(days=today.weekday())).isoformat(),  # Monday
        "month": today.replace(day=1).isoformat(),
    }


def _recruiting_for(conn, email: str, today: date) -> dict:
    starts = _period_starts(today)
    # "active" is the 12-day worked rule — the same one the Riders tab, the
    # active/idle filter and the drilldown use. It was the roster flag
    # (is_active) until 2026-09, which made the tile disagree with the list
    # behind it and with the word "active" everywhere else in the app. The
    # roster count is still here, under its own honest name.
    # The alias is load-bearing. active_person_sql builds a correlated subquery
    # over `transactions`, which has a person_id of its own; handed a bare
    # "person_id" the inner scope wins and the predicate becomes
    # `_wt.person_id = _wt.person_id` — always true — so the count silently
    # becomes "has anyone, anywhere, been paid recently".
    active = active_person_sql("rm.person_id")
    # A recruiter recruits PEOPLE, not rider ids. The counts used to be one
    # row of rider_master each, so a rider who also holds an id at a second
    # company scored twice — and the app papered over it with a footnote
    # ("N rider ids across M people"). Since the app grew a deliberate "add an
    # id at another company" action (2026-09-10) that double count is
    # something we cause, not something the data happens to contain, so the
    # unit is the person and the footnote is gone.
    #
    # Everything is derived from one row per person: the day they were FIRST
    # onboarded by this recruiter (a second id years later is not a new
    # recruit), and whether ANY of their ids is working or on the roster.
    per_person = (
        "SELECT rm.person_id AS pid, "
        "       MIN(substr(rm.created_at,1,10)) AS first_day, "
        f"      MAX(CASE WHEN {active} THEN 1 ELSE 0 END) AS working, "  # noqa: S608 - literal
        "       MAX(CASE WHEN rm.is_active=1 THEN 1 ELSE 0 END) AS on_roster "
        "FROM rider_master rm WHERE rm.recruited_by=? GROUP BY rm.person_id"
    )
    row = conn.execute(
        "SELECT COUNT(*) AS all_time, "
        "  COUNT(*) AS persons, "
        "  SUM(working) AS active, "
        "  SUM(on_roster) AS on_roster, "
        "  SUM(CASE WHEN first_day >= ? THEN 1 ELSE 0 END) AS today, "
        "  SUM(CASE WHEN first_day >= ? THEN 1 ELSE 0 END) AS week, "
        "  SUM(CASE WHEN first_day >= ? THEN 1 ELSE 0 END) AS month "
        f"FROM ({per_person}) p",  # noqa: S608 - per_person is built from literals
        # Order matters: the three date comparisons are in the SELECT list and
        # bind before the subquery's recruited_by, which is further down the
        # SQL string. Getting this backwards silently returns zeros.
        (starts["today"], starts["week"], starts["month"], email),
    ).fetchone()
    by_company = [
        {"company_name": r["company"], "riders": int(r["n"]), "active": int(r["a"] or 0)}
        for r in conn.execute(
            # DISTINCT here too: two ids at the SAME company is unusual but
            # legal (the placeholder id retired late, a company reissuing),
            # and the per-company column has to add up to the total above.
            "SELECT company, COUNT(DISTINCT person_id) AS n, "
            "  COUNT(DISTINCT CASE WHEN is_active=1 THEN person_id END) AS a "
            "FROM rider_master WHERE recruited_by=? GROUP BY company ORDER BY n DESC, company",
            (email,),
        )
    ]
    ev_holders = conn.execute(
        "SELECT COUNT(DISTINCT ea.person_id) FROM ev_assignments ea "
        "WHERE ea.returned_date IS NULL AND ea.person_id IN "
        "  (SELECT person_id FROM rider_master WHERE recruited_by=?)",
        (email,),
    ).fetchone()[0]
    recent = [
        {
            "rider_id": r["rider_id"],
            "company_name": r["company"],
            "name": r["name"],
            "person_id": r["person_id"],
            "hub": r["hub"],
            "created_at": r["created_at"],
            "is_active": bool(r["is_active"]),
        }
        for r in conn.execute(
            "SELECT rider_id, company, name, person_id, hub, created_at, is_active "
            "FROM rider_master WHERE recruited_by=? "
            "ORDER BY created_at DESC, rider_id DESC LIMIT 20",
            (email,),
        )
    ]
    return {
        "email": email,
        "as_of": today.isoformat(),
        "periods": starts,
        "counts": {
            "today": int(row["today"] or 0),
            "week": int(row["week"] or 0),
            "month": int(row["month"] or 0),
            "all_time": int(row["all_time"] or 0),
            "persons": int(row["persons"] or 0),
            "active": int(row["active"] or 0),
            "on_roster": int(row["on_roster"] or 0),
            "ev_holders": int(ev_holders or 0),
        },
        "by_company": by_company,
        "recent": recent,
    }


@router.get("/my-recruiting")
def my_recruiting(
    email: str | None = Query(None, description="admin only: another recruiter"),
    user: dict = Depends(get_current_user),
) -> dict:
    """The signed-in recruiter's onboarding numbers (today / this week / this
    month / all time), split by company, with their latest onboardings."""
    target = (user["email"] or "").lower()
    if email and email.lower() != target:
        with get_connection() as conn:
            row = conn.execute(
                "SELECT email, role, zone, is_head FROM users WHERE email=?", (email.lower(),)
            ).fetchone()
        # An admin, or a head recruiter over somebody in their own zone.
        if not supervises(user, dict(row) if row else None):
            raise HTTPException(403, "You can only look at your own numbers")
        target = email.lower()
    with get_connection() as conn:
        return _recruiting_for(conn, target, date.today())


@router.get("/zone-recruiting")
def zone_recruiting(
    zone: str | None = Query(None, description="admins may name a zone; a head cannot"),
    user: dict = Depends(get_current_user),
) -> dict:
    """A head recruiter's view of their own zone: one row per recruiter in it.

    The same numbers each recruiter sees on their own "My numbers" tab, side
    by side, for the people the head is responsible for. Drilling into a row
    is the existing ``/app/my-recruiting?email=`` — widened for heads at the
    same time as this, so there is one implementation of those counts rather
    than a second that can drift from it.

    Deliberately not a money route. A head is a recruiter, so the money fence
    applies to them exactly as it does to their team; what this adds is sight
    of colleagues' work, nothing about balances.
    """
    asked = (zone or "").strip().lower() or None
    if asked and asked.title() not in ZONES:
        raise HTTPException(400, f"zone must be one of {', '.join(ZONES)}")
    mine = heads_zone(user)
    if user["role"] in ("admin", "creator"):
        # An admin supervises any zone they name, and their own if they have
        # one. With neither there is no sensible default: "everybody" is the
        # console's recruiter board, not this.
        zone = asked or (user.get("zone") or "").strip().lower() or None
        if zone is None:
            raise HTTPException(400, "Name a zone")
    else:
        # A head is locked to their patch, exactly like every other zone-aware
        # route. Either not a head, or a head nobody has given a zone to; both
        # mean "you supervise nobody" and neither is worth distinguishing.
        if mine is None:
            raise HTTPException(403, "Not a head recruiter for any zone")
        if asked and asked != mine:
            raise HTTPException(403, "You can only see your own zone")
        zone = mine
    today = date.today()
    starts = _period_starts(today)
    active = active_person_sql("rm.person_id")
    rows = []
    with get_connection() as conn:
        staff = conn.execute(
            "SELECT u.email, u.display_name, u.is_active, p.full_name "
            "FROM users u LEFT JOIN recruiter_profiles p ON p.email = u.email "
            "WHERE u.role='recruiter' AND LOWER(COALESCE(u.zone,''))=? "
            "ORDER BY u.email",
            (zone,),
        ).fetchall()
        # One row per person, dated from their first id under that recruiter —
        # the same unit as _recruiting_for, so a head's view of somebody can
        # never disagree with that person's own screen.
        per_person = (
            "SELECT rm.person_id AS pid, "
            "       MIN(substr(rm.created_at,1,10)) AS first_day, "
            f"      MAX(CASE WHEN {active} THEN 1 ELSE 0 END) AS working, "
            "       MAX(CASE WHEN rm.is_active=1 THEN 1 ELSE 0 END) AS on_roster "
            "FROM rider_master rm WHERE rm.recruited_by=? GROUP BY rm.person_id"
        )
        for r in staff:
            email = r["email"]
            c = conn.execute(
                "SELECT COUNT(*) AS all_time, SUM(working) AS active, "
                "  SUM(on_roster) AS on_roster, "
                "  SUM(CASE WHEN first_day >= ? THEN 1 ELSE 0 END) AS today, "
                "  SUM(CASE WHEN first_day >= ? THEN 1 ELSE 0 END) AS week, "
                "  SUM(CASE WHEN first_day >= ? THEN 1 ELSE 0 END) AS month "
                f"FROM ({per_person}) p",  # noqa: S608 - built from literals
                (starts["today"], starts["week"], starts["month"], email),
            ).fetchone()
            evs = conn.execute(
                "SELECT COUNT(*) AS deployed, "
                "  COUNT(DISTINCT CASE WHEN returned_date IS NULL THEN person_id END) AS holding "
                "FROM ev_assignments WHERE assigned_by=?",
                (email,),
            ).fetchone()
            rows.append(
                {
                    "email": email,
                    "name": name_from(r["full_name"], r["display_name"], email),
                    "is_active": bool(r["is_active"]),
                    "today": int(c["today"] or 0),
                    "week": int(c["week"] or 0),
                    "month": int(c["month"] or 0),
                    "all_time": int(c["all_time"] or 0),
                    "active": int(c["active"] or 0),
                    "on_roster": int(c["on_roster"] or 0),
                    "evs_deployed": int(evs["deployed"] or 0),
                    "ev_holders": int(evs["holding"] or 0),
                }
            )
    rows.sort(key=lambda x: (-x["month"], -x["all_time"], x["email"]))
    return {
        "zone": zone.title(),
        "as_of": today.isoformat(),
        "periods": starts,
        "recruiters": rows,
        "totals": {
            k: sum(x[k] for x in rows)
            for k in ("today", "week", "month", "all_time", "active", "on_roster", "ev_holders")
        },
    }


@router.get("/recruiting")
def recruiting_board(user: dict = Depends(get_current_user)) -> dict:
    """Every recruiter's numbers side by side (admins / creator). Recruiters
    get only their own row, so the app can show the same screen to both."""
    today = date.today()
    starts = _period_starts(today)
    with get_connection() as conn:
        params: tuple[str, ...] = ()
        if user["role"] in ("admin", "creator"):
            where = "recruited_by IS NOT NULL AND recruited_by<>''"
        else:
            where, params = "recruited_by=?", ((user["email"] or "").lower(),)
        rows = [
            {
                "email": r["recruited_by"],
                "today": int(r["today"] or 0),
                "week": int(r["week"] or 0),
                "month": int(r["month"] or 0),
                "all_time": int(r["all_time"]),
                "active": int(r["active"] or 0),
            }
            for r in conn.execute(
                # People, not rider ids — the same unit as _recruiting_for and
                # the console board. Collapse to one row per (recruiter,
                # person) first, dated from that person's first id under them,
                # then count the rows.
                "SELECT recruited_by, COUNT(*) AS all_time, "
                "  SUM(on_roster) AS active, "
                "  SUM(CASE WHEN first_day >= ? THEN 1 ELSE 0 END) AS today, "
                "  SUM(CASE WHEN first_day >= ? THEN 1 ELSE 0 END) AS week, "
                "  SUM(CASE WHEN first_day >= ? THEN 1 ELSE 0 END) AS month "
                "FROM ("
                "  SELECT recruited_by, person_id, "
                "         MIN(substr(created_at,1,10)) AS first_day, "
                "         MAX(CASE WHEN is_active=1 THEN 1 ELSE 0 END) AS on_roster "
                f"  FROM rider_master WHERE {where} GROUP BY recruited_by, person_id"
                ") p GROUP BY recruited_by "
                "ORDER BY month DESC, all_time DESC, recruited_by",
                # The three dates are in the outer SELECT list, the WHERE
                # params are in the subquery further down the string.
                (starts["today"], starts["week"], starts["month"], *params),
            )
        ]
    return {"as_of": today.isoformat(), "periods": starts, "recruiters": rows}


# ── Things to do ─────────────────────────────────────────────────────────────
# The app's home screen. A recruiter's day is mostly legwork at the stores
# (hubs) of their zone: collecting COD that riders still hold, chasing EV
# holders with dues, and picking up EVs from riders who have gone inactive.
# Each item is one visit; they are grouped by store so a recruiter can plan a
# round. Zone defaults to the recruiter's own (users.zone); admins and
# recruiters with no zone see every store, labelled.

TODO_KINDS = ("cod", "ev_dues", "inactive_ev")


def _todo_rows(conn) -> list[dict]:
    rows = conn.execute(
        "SELECT pr.person_id, pr.display_name, "
        "       COALESCE(ea.cod_outstanding, 0) AS cod_outstanding, "
        "       COALESCE(ea.outstanding, 0) AS outstanding, "
        "       CASE WHEN COALESCE(b.current_balance, 0) < 0 "
        "            THEN -b.current_balance ELSE 0 END AS dues_outstanding, "
        "       a.ev_id, a.handover_date, m.model_name AS model, "
        "       (SELECT COUNT(*) FROM rider_master rm WHERE rm.person_id=pr.person_id "
        "          AND rm.is_active=1) AS active_ids, "
        "       (SELECT rm.hub FROM rider_master rm WHERE rm.person_id=pr.person_id "
        "          AND rm.hub IS NOT NULL AND rm.hub<>'' "
        "          ORDER BY rm.is_active DESC, rm.created_at DESC LIMIT 1) AS hub, "
        "       (SELECT ch.zone FROM rider_master rm "
        "          JOIN company_hubs ch ON ch.company=rm.company AND ch.hub=rm.hub "
        "          WHERE rm.person_id=pr.person_id AND ch.zone IS NOT NULL "
        "          ORDER BY rm.is_active DESC LIMIT 1) AS hub_zone, "
        "       (SELECT GROUP_CONCAT(DISTINCT rm.company) FROM rider_master rm "
        "          WHERE rm.person_id=pr.person_id AND rm.is_active=1) AS companies, "
        "       (SELECT rm.mob_no FROM rider_master rm WHERE rm.person_id=pr.person_id "
        "          AND rm.mob_no IS NOT NULL AND rm.mob_no<>'' "
        "          ORDER BY rm.is_active DESC LIMIT 1) AS mob_no, "
        "       (SELECT ru.zone FROM rider_master rm JOIN users ru ON ru.email=rm.recruited_by "
        "          WHERE rm.person_id=pr.person_id AND ru.zone IS NOT NULL LIMIT 1) "
        "          AS recruiter_zone, "
        # Distinct from recruiter_zone being NULL: that is also true of a rider
        # credited to a recruiter nobody has placed yet, who is somebody's
        # responsibility and not in the pool.
        "       (SELECT COUNT(*) FROM rider_master rm WHERE rm.person_id=pr.person_id "
        "          AND rm.recruited_by IS NOT NULL) AS credited "
        "FROM person_registry pr "
        "LEFT JOIN ev_arrears ea ON ea.person_id=pr.person_id "
        "LEFT JOIN balances b ON b.person_id=pr.person_id "
        "LEFT JOIN ev_assignments a ON a.person_id=pr.person_id AND a.returned_date IS NULL "
        "LEFT JOIN ev_units u ON u.ev_id=a.ev_id "
        "LEFT JOIN ev_models m ON m.model_id=u.model_id "
        "WHERE COALESCE(ea.cod_outstanding, 0) > 0 "
        "   OR (a.ev_id IS NOT NULL AND (COALESCE(ea.outstanding, 0) > 0 "
        "                                OR COALESCE(b.current_balance, 0) < 0)) "
        "   OR (a.ev_id IS NOT NULL AND NOT EXISTS "
        "        (SELECT 1 FROM rider_master rm WHERE rm.person_id=pr.person_id "
        "           AND rm.is_active=1)) "
        "ORDER BY pr.display_name"
    ).fetchall()
    items: list[dict] = []
    for r in rows:
        base = {
            "person_id": r["person_id"],
            "name": r["display_name"],
            "hub": r["hub"] or "",
            "companies": [c for c in (r["companies"] or "").split(",") if c],
            "mob_no": r["mob_no"],
            "ev_id": r["ev_id"],
            "ev_model": r["model"],
            "recruiter_zone": r["recruiter_zone"],
            "hub_zone": r["hub_zone"],
        }
        if int(r["cod_outstanding"] or 0) > 0:
            items.append(
                {
                    **base,
                    "kind": "cod",
                    "cod_outstanding": int(r["cod_outstanding"]),
                    "title": f"Collect COD · {r['display_name']}",
                }
            )
        total_dues = int(r["outstanding"] or 0) + int(r["dues_outstanding"] or 0)
        if r["ev_id"] and total_dues > 0:
            items.append(
                {
                    **base,
                    "kind": "ev_dues",
                    "outstanding": int(r["outstanding"] or 0),
                    "dues_outstanding": int(r["dues_outstanding"] or 0),
                    "total_dues": total_dues,
                    "title": f"EV dues · {r['display_name']} · {r['ev_id']}",
                }
            )
        if r["ev_id"] and int(r["active_ids"] or 0) == 0:
            items.append(
                {
                    **base,
                    "kind": "inactive_ev",
                    "handover_date": r["handover_date"],
                    "title": f"Collect {r['ev_id']} · {r['display_name']} is inactive",
                }
            )
    return items


@router.get("/todo")
def todo(
    zone: str | None = Query(None, description="North | South | all; default: my zone"),
    user: dict = Depends(get_current_user),
) -> dict:
    """What needs a visit, grouped by store (hub), for one zone.

    Fenced: field staff with a zone on their account get their own zone and
    nothing else, whatever they ask for — not Misc, and not the stores nobody
    has classified. See hubs.zone_scope for why those stopped riding along.
    """
    want = (zone or "").strip().lower()
    if not want:
        want = (user.get("zone") or "all").lower()
    if want not in ("all", "unassigned") and want.title() not in ZONES:
        raise HTTPException(400, f"zone must be one of {', '.join(ZONES)}, unassigned or all")
    fence = fenced_zone(user)
    if fence:
        # "unassigned" is not an escape hatch either — see hubs.zone_scope.
        if want not in ("all", fence):
            raise HTTPException(403, "You can only see your own zone")
        want = fence
    with get_connection() as conn:
        items = _todo_rows(conn)
    stores: dict[str, dict] = {}
    for it in items:
        # A store's zone; a hub-less rider (Blitz and co.) sits in "Misc"
        # under the zone of the recruiter who onboarded them.
        hub_zone = it.get("hub_zone") or it.get("recruiter_zone")
        if want == "unassigned" and hub_zone:
            continue
        # A fenced caller keeps the unassigned pool — riders with no store
        # and nobody credited, for whom no zone could ever be derived. See
        # hubs.unassigned_pool_sql.
        in_pool = not (it.get("hub") or "").strip() and not it.get("credited")
        if (
            want not in ("all", "unassigned")
            and (hub_zone or "").lower() != want
            and not (fence and in_pool)
        ):
            continue
        store = stores.setdefault(
            it["hub"] or "Misc",
            {"hub": it["hub"] or "Misc", "zone": hub_zone, "items": []},
        )
        store["items"].append(it)
    # Counts are keyed "<kind>_items" so the money middleware never mistakes
    # them for amounts (``cod`` is a money key).
    counts = {f"{k}_items": 0 for k in TODO_KINDS}
    for s in stores.values():
        for it in s["items"]:
            counts[f"{it['kind']}_items"] += 1
    ordered = sorted(stores.values(), key=lambda s: (-len(s["items"]), s["hub"]))
    return {
        "zone": want.title() if want not in ("all", "unassigned") else want,
        "my_zone": user.get("zone"),
        "as_of": date.today().isoformat(),
        "counts": {**counts, "total": sum(counts.values()), "stores": len(ordered)},
        "stores": ordered,
    }


# ── Recruiter location ("Option 1" tracking) ─────────────────────────────────
# The app records where a recruiter is each time they open it — never in the
# background — and the server keeps at most one row per 30 minutes per
# account, whatever the phone sends. Admins read the trail on the web.

LOCATION_MIN_GAP_MIN = 30


class LocationIn(BaseModel):
    lat: float
    lng: float
    accuracy_m: float | None = None
    area: str | None = None  # reverse-geocoded on the phone ("Salt Lake, Kolkata")
    source: str = "app_open"


@router.post("/location")
def record_location(body: LocationIn, user: dict = Depends(get_current_user)) -> dict:
    if not (-90 <= body.lat <= 90 and -180 <= body.lng <= 180):
        raise HTTPException(400, "lat/lng out of range")
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with get_connection() as conn:
        last = conn.execute(
            "SELECT at FROM recruiter_locations WHERE email=? ORDER BY id DESC LIMIT 1",
            (user["email"],),
        ).fetchone()
        if last and last["at"]:
            try:
                last_at = datetime.fromisoformat(str(last["at"]).replace("T", " ")[:19])
            except ValueError:
                last_at = None
            if last_at and now - last_at < timedelta(minutes=LOCATION_MIN_GAP_MIN):
                nxt = last_at + timedelta(minutes=LOCATION_MIN_GAP_MIN)
                return {
                    "recorded": False,
                    "last_at": last_at.isoformat(timespec="seconds"),
                    "next_after": nxt.isoformat(timespec="seconds"),
                }
        conn.execute(
            "INSERT INTO recruiter_locations (email, at, lat, lng, accuracy_m, area, source) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                user["email"],
                now.strftime("%Y-%m-%d %H:%M:%S"),
                body.lat,
                body.lng,
                body.accuracy_m,
                (body.area or "").strip()[:120] or None,
                (body.source or "app_open")[:40],
            ),
        )
        conn.commit()
    return {
        "recorded": True,
        "last_at": now.isoformat(timespec="seconds"),
        "next_after": (now + timedelta(minutes=LOCATION_MIN_GAP_MIN)).isoformat(timespec="seconds"),
    }


@router.get("/locations")
def list_locations(
    email: str | None = Query(None, description="admin only: another recruiter"),
    since: str | None = Query(None, description="ISO date/time lower bound"),
    limit: int = Query(200, ge=1, le=2000),
    user: dict = Depends(get_current_user),
) -> list[dict]:
    """A recruiter's location trail — their own, or anyone's for admins."""
    target = user["email"]
    if email and email.strip().lower() != target:
        if user["role"] not in ("admin", "creator"):
            raise HTTPException(403, "Only admins can see another recruiter's locations")
        target = email.strip().lower()
    where, params = ["email=?"], [target]
    if since:
        where.append("at>=?")
        params.append(since.replace("T", " "))
    params.append(limit)
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, email, at, lat, lng, accuracy_m, area, source FROM recruiter_locations "
            f"WHERE {' AND '.join(where)} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


# ── crash reports from the phone ─────────────────────────────────────────────
# An app that dies on launch cannot be debugged from the office: there is no
# logcat on a recruiter's phone, and the recruiter is in a store. So the app
# posts its own last breath here — the start-up breadcrumb trail and the stack
# trace, if there was one. Unauthenticated on purpose: the crash usually
# happens before anyone can sign in. Rate-limited and size-capped instead.
_crash_limit = rate_limit("app-crash", limit=40, window_seconds=3600)


class CrashIn(BaseModel):
    version: str | None = Field(default=None, max_length=80)
    device: str | None = Field(default=None, max_length=200)
    android: str | None = Field(default=None, max_length=80)
    kind: str = Field(default="crash", max_length=20)  # crash | trail
    email: str | None = Field(default=None, max_length=200)  # if the app knew
    trail: str | None = Field(default=None, max_length=8000)
    detail: str | None = Field(default=None, max_length=16000)


@router.post("/crash", status_code=201, dependencies=[Depends(_crash_limit)])
def record_crash(body: CrashIn) -> dict:
    """Store one start-up failure. Returns its id so the phone can say it sent."""
    kind = body.kind.strip().lower()
    if kind not in ("crash", "trail"):
        kind = "crash"
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO app_crashes (version, device, android, kind, email, trail, detail) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                (body.version or "").strip()[:80] or None,
                (body.device or "").strip()[:200] or None,
                (body.android or "").strip()[:80] or None,
                kind,
                (body.email or "").strip().lower()[:200] or None,
                (body.trail or "").strip()[:8000] or None,
                (body.detail or "").strip()[:16000] or None,
            ),
        )
        rid = cur.lastrowid
        conn.commit()
    return {"id": rid, "stored": True}


@router.get("/crashes")
def list_crashes(
    limit: int = Query(50, ge=1, le=500),
    user: dict = Depends(get_current_user),
) -> list[dict]:
    """The phones' crash reports, newest first (admins and creators)."""
    if user["role"] not in ("admin", "creator"):
        raise HTTPException(403, "Admins only")
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, at, version, device, android, kind, email, trail, detail "
            "FROM app_crashes ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.get("/person/{person_id}/timeline")
def person_timeline(
    person_id: int,
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
) -> list[dict]:
    """Everything that has happened to one rider, newest first: added, edited,
    EV handed over, returned, sent for repair, closed out, documents, referrals.

    This is the same activity feed the console reads, but scoped to a person
    rather than to an operator. ``/api/activity`` deliberately confines a
    recruiter to rows they wrote themselves — that keeps one recruiter out of
    another's day — but a rider's own history has to show every hand that
    touched them, or the timeline lies by omission the moment a colleague
    hands over the EV.
    """
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, at, email, role, action, entity_type, entity_id, entity_label, "
            "       details, lat, lng "
            "FROM activity_log WHERE person_id=? ORDER BY id DESC LIMIT ?",
            (person_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["action_label"] = ACTIONS.get(d["action"], d["action"])
        if d.get("details"):
            try:
                d["details"] = json.loads(d["details"])
            except (TypeError, ValueError):
                d["details"] = None
        out.append(d)
    return out
