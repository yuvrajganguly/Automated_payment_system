"""The provider's weekly bill, reconciled against our own books (2026-09-12).

The tally that already existed answers "does their arithmetic match ours" out
of ev_daily_ledger. This answers the question the office actually asks on a
Monday: for each vehicle they billed, did we charge a rider, and did that rider
pay? Reconciling week 36 by hand taught five rules, and each one is here
because getting it wrong understated what we had collected.
"""

from __future__ import annotations

import io

import pytest

from payout.domain.provider_bill import full_week_rates, reconcile, same_person
from tests.conftest import assign, make_ev, make_person, make_rider

WEEK = ("2026-09-01", "2026-09-07")


def _rent(db, pid, *, charged=0, collected=0, missed=0, recovered=0, cycle=WEEK, by="office"):
    """Book the rent events a payout run would have written."""
    for event, amount in (
        ("RENT", -charged),
        ("RENT_COLLECTED", collected),
        ("RENT_MISSED", -missed),
        ("RENT_RECOVERED", recovered),
    ):
        if amount:
            db.execute(
                "INSERT INTO transactions "
                "(person_id, event_type, amount, balance_after, cycle_start, cycle_end, "
                " created_by) VALUES (?,?,?,0,?,?,?)",
                (pid, event, amount, cycle[0], cycle[1], by),
            )


def _line(ev_id, amount, *, name=None, remark=None, no=1):
    return {
        "line_no": no,
        "ev_id": ev_id,
        "vin": None,
        "provider_name": name,
        "amount": amount,
        "remark": remark,
        "deploy_date": None,
    }


def _by_ev(report):
    return {r["ev_id"]: r for r in report["rows"]}


# ── the rules ────────────────────────────────────────────────────────────────


def test_arrears_recovered_counts_as_collected(db):
    """The money came in. It came out of arrears instead of that week's
    payout, but it came in — and reading the two columns apart made a settled
    week look like a debt, which is what made "collected" read low."""
    pid = make_person(db, "Moti Mondal")
    make_rider(db, pid, "R-1", "Jiffy", "Moti Mondal")
    assign(db, pid, make_ev(db, "EV-A", provider="Raft", model="Blue"), handover="2026-08-01")
    # The real shape, from week 36: the payout covered 1,110 of the 1,295 and
    # the remaining 185 was booked missed, then recovered out of arrears. RENT
    # and RENT_MISSED are disjoint parts of one week's rent, which is why the
    # charge is their sum.
    _rent(db, pid, charged=111_000, collected=111_000, missed=18_500, recovered=18_500)
    db.commit()
    r = _by_ev(reconcile(db, [_line("EV-A", 122_500, name="MOTI MONDAL")], *WEEK))["EV-A"]
    assert r["charged"] == 129_500, "1,110 taken from the payout plus 185 missed"
    assert r["collected"] == 129_500, "111,000 + 18,500 recovered is the whole week"
    assert r["missed"] is None
    assert r["tag"] == "Collected"


def test_a_person_billed_for_two_units_has_their_charge_split(db):
    """One rider carried RENT 2500 across two vehicles. Printing 2500 against
    both doubled him; the bigger unit must not swallow the whole payment."""
    pid = make_person(db, "Somnath Sardar")
    make_rider(db, pid, "R-2", "Jiffy", "Somnath Sardar")
    assign(db, pid, make_ev(db, "AV118", provider="Raft", model="Regular"), handover="2026-08-01")
    make_ev(db, "CBICEVD0005", provider="Raft", model="Blue")
    _rent(db, pid, charged=254_500, collected=254_500)
    db.commit()
    rows = _by_ev(
        reconcile(
            db,
            [
                _line("AV118", 105_000, name="SOMNATH SARDAR", no=1),
                _line("CBICEVD0005", 122_500, name="SOMNATH SARDAR", no=2),
            ],
            *WEEK,
        )
    )
    assert rows["AV118"]["charged"] + rows["CBICEVD0005"]["charged"] == 254_500
    assert rows["AV118"]["charged"] < rows["CBICEVD0005"]["charged"], "split by each unit's rate"


def test_expected_is_our_daily_rate_times_the_days_they_billed(db):
    """Their full week divided by seven is their daily rate; their amount over
    that is the days. A Blue billed 350 of 1,225 is two days, and two days at
    our 1,295 a week is 370."""
    make_ev(db, "EV-P", provider="Raft", model="Blue")
    db.commit()
    lines = [_line("EV-FULL", 122_500, no=1), _line("EV-P", 35_000, no=2)]
    # EV-FULL is the week's full-rate line, which is what calibrates the rest.
    make_ev(db, "EV-FULL", provider="Raft", model="Blue")
    db.commit()
    rows = _by_ev(reconcile(db, lines, *WEEK))
    assert rows["EV-P"]["days"] == 2
    assert rows["EV-P"]["expected"] == 37_000
    assert rows["EV-FULL"]["expected"] == 129_500


def test_a_returned_unit_still_has_an_expected_figure(db):
    """A vehicle out for three days earns three days of rent whatever happened
    to it afterwards."""
    ev = make_ev(db, "EV-R", provider="Raft", model="Regular", status="returned")
    make_ev(db, "EV-RFULL", provider="Raft", model="Regular")
    db.commit()
    rows = _by_ev(reconcile(db, [_line("EV-RFULL", 105_000, no=1), _line(ev, 45_000, no=2)], *WEEK))
    assert rows["EV-R"]["days"] == 3
    assert rows["EV-R"]["expected"] == 53_571  # 125,000 / 7 * 3
    assert rows["EV-R"]["tag"] == "Returned"


def test_a_correction_beats_everything_derived(db):
    """Which vehicles actually came back is not in the tables. The office says
    so, and what the office says wins."""
    pid = make_person(db, "Pinki Mondal")
    make_rider(db, pid, "R-3", "Jiffy", "Pinki Mondal")
    assign(db, pid, make_ev(db, "EV-O", provider="Raft", model="Blue"), handover="2026-08-01")
    _rent(db, pid, charged=129_500, missed=129_500)
    db.commit()
    plain = _by_ev(reconcile(db, [_line("EV-O", 122_500, name="PINKI MONDAL")], *WEEK))["EV-O"]
    assert plain["tag"] == "Not collected"
    fixed = _by_ev(
        reconcile(
            db,
            [_line("EV-O", 122_500, name="PINKI MONDAL")],
            *WEEK,
            overrides={"EV-O": {"tag": "Returned", "note": "came back on the 3rd"}},
        )
    )["EV-O"]
    assert fixed["tag"] == "Returned"
    assert fixed["note"] == "came back on the 3rd"
    assert fixed["overridden"] == ["note", "tag"]


def test_rent_cleared_by_hand_is_not_a_due(db):
    """Charged, missed by the payout, then settled outside any cycle. A
    single-day cycle is how those are booked."""
    pid = make_person(db, "MD Sain")
    make_rider(db, pid, "R-4", "Jiffy", "MD Sain")
    assign(db, pid, make_ev(db, "EV-H", provider="Raft", model="Blue"), handover="2026-08-01")
    _rent(db, pid, charged=111_000, missed=111_000)
    _rent(db, pid, recovered=111_000, cycle=("2026-09-02", "2026-09-02"), by="yuvraj@x.test")
    db.commit()
    r = _by_ev(reconcile(db, [_line("EV-H", 87_500, name="MD SAIN")], *WEEK))["EV-H"]
    assert r["missed"] is None
    assert r["tag"] == "Paid Manually"
    assert "cleared by hand" in r["note"]


def test_a_damage_line_is_not_a_rent_question(db):
    make_ev(db, "EV-D", provider="Raft", model="Blue")
    db.commit()
    r = _by_ev(reconcile(db, [_line("EV-D", 248_000, remark="DAMAGE CHARGE")], *WEEK))["EV-D"]
    assert r["tag"] == "Damage"
    assert r["damage"] == 248_000
    assert r["expected"] is None


def test_a_unit_they_bill_that_nobody_was_charged_for_says_so(db):
    make_ev(db, "EV-N", provider="Raft", model="Blue", status="spare")
    db.commit()
    r = _by_ev(reconcile(db, [_line("EV-N", 122_500, name="SOMEBODY")], *WEEK))["EV-N"]
    assert r["tag"] == "Not collected"
    assert "no rider was charged for it" in r["note"]


# ── the name matcher ────────────────────────────────────────────────────────


def test_transliteration_is_not_a_dispute():
    """Raft and we spell Bengali names differently. An exact match would call
    one man two people and fill the report with disputes that are not."""
    assert same_person("Bijoy Das", "BIJAY DAS")
    assert same_person("Subhadip Biswas", "SUBHADEEP BISWAS")
    assert same_person("Hritick Sarkar", "HRITIK SARKAR")
    assert same_person("MainuddinSha", "MAINUDDIN SHA"), "one side ran the name together"


def test_a_shared_surname_is_not_a_shared_identity():
    """The harder half, and the case the whole feature exists for. Somnath
    Sardar and Milon Sardar score 0.81 as whole strings and are two different
    men sharing one person record — found because Raft billed both their
    vehicles and the names on the bill did not match each other."""
    assert not same_person("Somnath Sardar", "MILON SARDAR")
    assert not same_person("Surjo Halder", "KOUSHIK HALDER")
    assert not same_person("Rahul yadav", "RAHUL DAS")
    assert not same_person("Jeet Ghosh", "ANAND SHAW")
    assert not same_person("Pradip Ray", "SK NASIRUDDIN")


def test_the_full_week_rate_comes_from_the_bill_itself():
    """So a provider's price rise needs no code change, and cannot silently
    skew a whole week's Expected."""
    lines = [
        {"model": "Blue", "amount": 122_500},
        {"model": "Blue", "amount": 35_000},
        {"model": "Blue", "amount": 248_000, "is_damage": True},
        {"model": "Regular", "amount": 105_000},
    ]
    assert full_week_rates(lines) == {"Blue": 122_500, "Regular": 105_000}


# ── the HTTP skin ───────────────────────────────────────────────────────────


@pytest.fixture
def client(db):
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from payout.api import ratelimit
    from payout.api.app import app
    from payout.auth import hash_password

    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("boss@t.test", hash_password("Creator-pass-1"), "creator"),
    )
    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        ("rec@t.test", hash_password("Recruit-pass-1"), "recruiter"),
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app) as c:
        yield c


def _hdr(client, email="boss@t.test", pw="Creator-pass-1"):
    r = client.post("/api/auth/login", data={"username": email, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _bill_file() -> bytes:
    import pandas as pd

    buf = io.BytesIO()
    pd.DataFrame(
        [
            {
                "Sr": 1,
                "Deployment Date": "01-Aug-26",
                "EV ID": "EV-W1",
                "VIN": "RCEV/K1/00001",
                "DP Name": "MOTI MONDAL",
                "Amount": "1225",
                "Remark": "",
            },
            {
                "Sr": 2,
                "Deployment Date": "05-Sep-26",
                "EV ID": "EV-W2",
                "VIN": "RCEV/K1/00002",
                "DP Name": "NOBODY HERE",
                "Amount": "175",
                "Remark": "",
            },
        ]
    ).to_excel(buf, index=False)
    return buf.getvalue()


def test_upload_then_reconcile_over_http(db, client):
    pytest.importorskip("pandas")
    pid = make_person(db, "Moti Mondal")
    make_rider(db, pid, "R-9", "Jiffy", "Moti Mondal")
    assign(db, pid, make_ev(db, "EV-W1", provider="Raft", model="Blue"), handover="2026-08-01")
    make_ev(db, "EV-W2", provider="Raft", model="Blue", status="spare")
    _rent(db, pid, charged=111_000, collected=111_000, missed=18_500, recovered=18_500)
    db.commit()
    boss = _hdr(client)

    up = client.post(
        "/api/providers/Raft/bills",
        data={"period_start": WEEK[0], "period_end": WEEK[1]},
        files={"file": ("raft.xlsx", _bill_file(), "application/vnd.ms-excel")},
        headers=boss,
    )
    assert up.status_code == 200, up.text
    bill_id = up.json()["bill_id"]

    got = client.get(f"/api/providers/Raft/bills/{bill_id}/reconciliation", headers=boss)
    assert got.status_code == 200, got.text
    body = got.json()
    rows = {r["ev_id"]: r for r in body["rows"]}
    # Money comes out in rupees: the middleware rupeeizes on the way through.
    assert rows["EV-W1"]["collected"] == 1295.0
    assert rows["EV-W1"]["tag"] == "Collected"
    assert rows["EV-W2"]["tag"] == "Not collected"
    assert body["totals"]["billed"] == 1400.0
    # The rider's name as Raft has it is kept now, which is the whole point.
    assert rows["EV-W1"]["provider_name"] == "MOTI MONDAL"

    # A correction sticks, and is keyed to the vehicle.
    pa = client.patch(
        f"/api/providers/Raft/bills/{bill_id}/lines/EV-W2",
        json={"field": "tag", "value": "Returned", "note": "came back in August"},
        headers=boss,
    )
    assert pa.status_code == 200, pa.text
    again = client.get(f"/api/providers/Raft/bills/{bill_id}/reconciliation", headers=boss).json()
    assert {r["ev_id"]: r["tag"] for r in again["rows"]}["EV-W2"] == "Returned"

    # A bad field is refused rather than quietly inventing a column.
    bad = client.patch(
        f"/api/providers/Raft/bills/{bill_id}/lines/EV-W2",
        json={"field": "whatever", "value": "x"},
        headers=boss,
    )
    assert bad.status_code == 400

    xl = client.post(f"/api/providers/Raft/bills/{bill_id}/reconciliation/export", headers=boss)
    assert xl.status_code == 200
    assert xl.content[:2] == b"PK"


def test_a_recruiter_cannot_see_the_bill(client):
    """Whole-fleet money with every rider's name on it — the same reasoning
    that keeps bulk exports away from field staff."""
    rec = _hdr(client, "rec@t.test", "Recruit-pass-1")
    assert client.get("/api/providers/Raft/bills", headers=rec).status_code == 403
    assert client.get("/api/providers/Raft/bills/1/reconciliation", headers=rec).status_code == 403


# ── the period view, repaired ───────────────────────────────────────────────
#
# It is a collection rate, not a reconciliation: nothing external enters it, so
# a provider over-billing us cannot appear. What it CAN do is say whether the
# fleet paid for itself, and it was failing at that in three ways.


def _day(db, ev_id, day, *, pid=None, provider_cost=18_500, daily_cost=18_500, status="billed"):
    db.execute(
        "INSERT INTO ev_daily_ledger "
        "(ev_id, day, state, assigned_person_id, daily_cost, provider_cost, billing_status) "
        "VALUES (?,?,?,?,?,?,?)",
        (ev_id, day, "billable", pid, daily_cost, provider_cost, status),
    )


def test_the_days_nobody_was_billed_for_are_reported(db):
    """The old query filtered assigned_person_id IS NOT NULL, so a unit sitting
    on our books unassigned produced no row at all — and in week 36 that was
    the largest single class of disputed money."""
    from payout.domain.reconciliation import provider_rider_reconciliation

    pid = make_person(db, "Held Rider")
    make_rider(db, pid, "RR-1", "Jiffy", "Held Rider")
    make_ev(db, "EV-HELD", provider="Raft", model="Blue")
    make_ev(db, "EV-IDLE", provider="Raft", model="Blue", status="spare")
    for d in ("2026-09-01", "2026-09-02"):
        _day(db, "EV-HELD", d, pid=pid)
        _day(db, "EV-IDLE", d, pid=None, daily_cost=0)
    db.commit()

    out = provider_rider_reconciliation(db, "Raft", *WEEK)
    assert [r["name"] for r in out["rows"]] == ["Held Rider"]
    assert [u["ev_id"] for u in out["unheld"]] == ["EV-IDLE"]
    assert out["unheld"][0]["days"] == 2
    assert out["unheld"][0]["provider_owed"] == 37_000
    assert out["totals"]["unheld_owed"] == 37_000
    assert out["totals"]["unheld_evs"] == 1


def test_cost_to_us_is_in_the_rows(db):
    """daily_cost is what we could bill a rider; provider_cost is what the
    vehicle costs us regardless. Only the first was in the report, so the
    number that decides whether a unit pays for itself was missing from the
    report about whether units pay for themselves."""
    from payout.domain.reconciliation import provider_rider_reconciliation

    pid = make_person(db, "Workshop Rider")
    make_rider(db, pid, "RR-2", "Jiffy", "Workshop Rider")
    make_ev(db, "EV-WS", provider="Raft", model="Blue")
    # Two days on the road and billed; five the vehicle cost us and nobody
    # could be charged for, because it was in the workshop.
    for d in ("2026-09-01", "2026-09-02"):
        _day(db, "EV-WS", d, pid=pid)
    for d in ("2026-09-03", "2026-09-04", "2026-09-05", "2026-09-06", "2026-09-07"):
        _day(db, "EV-WS", d, pid=pid, daily_cost=0, status=None)
    db.commit()

    r = provider_rider_reconciliation(db, "Raft", *WEEK)["rows"][0]
    assert r["expected"] == 37_000, "we only ever asked him for the two days"
    assert r["collected"] == 37_000
    assert r["provider_owed"] == 129_500, "the vehicle cost us the whole week"
    assert r["collection_pct"] == 100.0, "he paid everything he was asked for"
    assert r["recovery_pct"] < 30, "and the unit still lost money — the honest number"
