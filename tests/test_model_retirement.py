"""Retiring an EV model, and switching a rider id off (2026-09-23).

Eight vehicles reached the fleet recorded as Blive Standard with `CBICEVD`
IDs — the Raft Blue pattern — each one quietly billing 1,260 a week instead
of 1,295. The office has stopped taking Blive units, so the durable fix is to
stop offering the choice rather than to train people harder.

The second half is the roster switch. A rider keeps an id at every company
they have ever worked for, and the engine charges EV rent to anyone holding a
vehicle who still has an *active* id at the company being processed. So one
week at Jiffy in March means a week's rent every time Jiffy runs, for ever.
The column that fixes it already existed and the engine already honoured it;
nothing could set it.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient  # noqa: E402

from payout.api import ratelimit  # noqa: E402
from payout.api.app import app  # noqa: E402
from payout.auth import hash_password  # noqa: E402
from tests.conftest import make_person, make_rider  # noqa: E402

_CREATOR = ("owner@t.test", "Owner-pass-1", "creator")


@pytest.fixture
def client(db):
    db.execute(
        "INSERT INTO users (email, password_hash, role, is_active) VALUES (?,?,?,1)",
        (_CREATOR[0], hash_password(_CREATOR[1]), _CREATOR[2]),
    )
    db.commit()
    ratelimit.reset()
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _login(client):
    r = client.post("/api/auth/login", data={"username": _CREATOR[0], "password": _CREATOR[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


def _model_id(db, provider, name):
    return db.execute(
        "SELECT model_id FROM ev_models WHERE provider=? AND model_name=?", (provider, name)
    ).fetchone()["model_id"]


def _retire(client, h, db, provider="Blive", name="Standard"):
    r = client.patch(
        f"/api/creator/ev-models/{_model_id(db, provider, name)}",
        json={"is_active": False},
        headers=h,
    )
    assert r.status_code == 200, r.text


# ── retiring a model ─────────────────────────────────────────────────────────
def test_a_retired_model_leaves_both_pickers(client, db):
    """The app takes the FIRST entry of this list as its default, so what the
    server sends is the picker — which is how the default changes on phones
    nobody can update."""
    h = _login(client)
    before = [
        m["model_name"] for m in client.get("/api/app/bootstrap", headers=h).json()["ev_models"]
    ]
    assert "Standard" in before

    _retire(client, h, db)

    models = client.get("/api/app/bootstrap", headers=h).json()["ev_models"]
    assert all(m["provider"] != "Blive" for m in models)
    assert (models[0]["provider"], models[0]["model_name"]) == ("Raft", "Blue"), (
        "Raft Blue has to be first, because first is what the app preselects"
    )


def test_the_console_still_lists_a_retired_model_but_last(client, db):
    """An existing unit shows its model by name, so hiding it outright would
    leave the console unable to explain what a vehicle is on."""
    h = _login(client)
    _retire(client, h, db)
    models = client.get("/api/evs/models", headers=h).json()
    blive = [m for m in models if m["provider"] == "Blive"]
    assert blive and blive[0]["is_active"] is False
    assert models[-1]["provider"] == "Blive"


def test_a_new_unit_on_a_retired_model_is_refused(client, db):
    h = _login(client)
    _retire(client, h, db)
    r = client.post(
        "/api/evs", json={"ev_id": "KOL9999", "provider": "Blive", "model": "Standard"}, headers=h
    )
    assert r.status_code == 409
    assert "retired" in r.json()["detail"]


def test_units_already_on_a_retired_model_keep_working(client, db):
    """Retiring is about what can be created next, never about what exists."""
    h = _login(client)
    assert (
        client.post(
            "/api/evs",
            json={"ev_id": "KOL1234", "provider": "Blive", "model": "Standard"},
            headers=h,
        ).status_code
        == 201
    )
    _retire(client, h, db)
    unit = client.get("/api/evs", headers=h).json()
    mine = [u for u in unit if u["ev_id"] == "KOL1234"]
    assert mine and float(mine[0]["weekly_rate"]) == 1260.0


def test_editing_a_rate_cannot_silently_un_retire_a_model(client, db):
    """The console's rate editor sends one field. Before the patch was made
    partial, any client that did not know about is_active or id_prefix reset
    them to the defaults just by touching something else."""
    h = _login(client)
    mid = _model_id(db, "Raft", "Blue")
    client.patch(f"/api/creator/ev-models/{mid}", json={"is_active": False}, headers=h)
    client.patch(f"/api/creator/ev-models/{mid}", json={"weekly_rate": 1400}, headers=h)
    row = db.execute(
        "SELECT weekly_rate, is_active, id_prefix FROM ev_models WHERE model_id=?", (mid,)
    ).fetchone()
    assert int(row["weekly_rate"]) == 140000
    assert int(row["is_active"]) == 0, "the rate edit un-retired the model"
    assert row["id_prefix"] == "CBICEVD", "the rate edit cleared the ID pattern"


# ── the wrong-model check ────────────────────────────────────────────────────
def test_a_unit_whose_id_belongs_to_another_model_is_flagged(db):
    """Exactly the eight: a CBICEVD id sitting on Blive Standard."""
    from payout.domain.anomalies import run_checks

    db.execute(
        "INSERT INTO ev_units (ev_id, model_id, status) VALUES ('CBICEVD0292', ?, 'in_use')",
        (_model_id(db, "Blive", "Standard"),),
    )
    db.commit()
    hits = [f for f in run_checks(db) if f["check"] == "ev_on_the_wrong_model"]
    assert len(hits) == 1
    assert "CBICEVD0292" in hits[0]["detail"]
    assert "Raft Blue" in hits[0]["detail"], "it should say what the id looks like"
    assert hits[0]["severity"] == "money"


def test_a_unit_on_a_model_with_no_known_pattern_is_not_flagged(db):
    """Raft Regular has no prefix on file. Absence of a rule is not a breach
    of one."""
    from payout.domain.anomalies import run_checks

    db.execute(
        "INSERT INTO ev_units (ev_id, model_id, status) VALUES ('ANYTHING-1', ?, 'spare')",
        (_model_id(db, "Raft", "Regular"),),
    )
    db.commit()
    assert not [f for f in run_checks(db) if f["check"] == "ev_on_the_wrong_model"]


# ── switching a rider id off ─────────────────────────────────────────────────
def test_a_rider_id_can_be_switched_off_and_back_on(client, db):
    h = _login(client)
    pid = make_person(db, "Moved To Myntra")
    make_rider(db, pid, "J-1", "Jiffy", "Moved To Myntra")
    db.commit()

    r = client.patch("/api/riders/J-1?company=Jiffy", json={"is_active": False}, headers=h)
    assert r.status_code == 200, r.text
    assert (
        int(db.execute("SELECT is_active FROM rider_master WHERE rider_id='J-1'").fetchone()[0])
        == 0
    )

    client.patch("/api/riders/J-1?company=Jiffy", json={"is_active": True}, headers=h)
    assert (
        int(db.execute("SELECT is_active FROM rider_master WHERE rider_id='J-1'").fetchone()[0])
        == 1
    )


def test_switching_off_leaves_the_id_its_history(db, client):
    """It is a roster flag, not a delete. The money stays exactly where it is."""
    h = _login(client)
    pid = make_person(db, "One Week In March")
    make_rider(db, pid, "J-2", "Jiffy", "One Week In March")
    db.execute(
        "INSERT INTO transactions (person_id, rider_id, company, cycle_start, cycle_end, "
        "event_type, amount, balance_after) VALUES (?, 'J-2', 'Jiffy', '2026-03-02', "
        "'2026-03-08', 'PAYOUT', 5000, 0)",
        (pid,),
    )
    db.commit()
    client.patch("/api/riders/J-2?company=Jiffy", json={"is_active": False}, headers=h)
    assert (
        db.execute("SELECT COUNT(*) AS n FROM transactions WHERE rider_id='J-2'").fetchone()["n"]
        == 1
    )
    assert (
        db.execute("SELECT COUNT(*) AS n FROM rider_master WHERE rider_id='J-2'").fetchone()["n"]
        == 1
    )


# ── what switching off actually stops ────────────────────────────────────────
def test_a_switched_off_id_stops_the_rent_at_that_company(db):
    """The complaint, end to end.

    A rider did one week at Kaptan months ago and has been on Myntra since. He
    holds an EV, so every Kaptan run charges him a full week's rent through the
    absent-rider loop in ``domain/engine.py`` — he is not in the payout file,
    but he still has a live id at the company, so the loop bills him.

    This proves the flag actually reaches that loop, rather than merely being
    stored. The Myntra id is untouched: he really does owe rent there.
    """
    import io
    from datetime import date, timedelta

    from openpyxl import Workbook

    from payout.domain.engine import process_cycle
    from tests.conftest import assign, make_ev

    def sheet(rows):
        wb = Workbook()
        ws = wb.active
        ws.append(["rider_id", "net_pay"])
        for r in rows:
            ws.append(list(r))
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    week = date.today() - timedelta(days=date.today().weekday(), weeks=1)
    pid = make_person(db, "Left Kaptan In March", balance=0, arrears=0)
    make_rider(db, pid, "K-OLD", "Kaptan", "Left Kaptan In March")
    make_rider(db, pid, "M-NOW", "Myntra", "Left Kaptan In March")
    make_ev(db, "CBICEVD0292", provider="Raft", model="Blue", status="in_use")
    assign(db, pid, "CBICEVD0292", charged_through=(week - timedelta(days=1)).isoformat())
    db.commit()

    def rent_rows():
        return db.execute(
            "SELECT COUNT(*) AS n FROM transactions WHERE person_id=? AND company='Kaptan' "
            "AND event_type IN ('RENT', 'RENT_MISSED')",
            (pid,),
        ).fetchone()["n"]

    # As things stand, running Kaptan without him in the file still bills him.
    process_cycle("Kaptan", week, week + timedelta(days=6), sheet([]), commit=True)
    assert rent_rows() > 0, "fixture is wrong — the absent-rider loop did not fire"

    before = rent_rows()
    db.execute("UPDATE rider_master SET is_active=0 WHERE rider_id='K-OLD'")
    db.commit()

    nxt = week + timedelta(days=7)
    process_cycle("Kaptan", nxt, nxt + timedelta(days=6), sheet([]), commit=True)
    assert rent_rows() == before, "a switched-off id was still charged rent at Kaptan"

    # And he is still on the hook where he actually works.
    assert (
        db.execute("SELECT is_active FROM rider_master WHERE rider_id='M-NOW'").fetchone()[
            "is_active"
        ]
        == 1
    )


# ── the retag script ─────────────────────────────────────────────────────────
def test_retag_moves_a_unit_to_the_model_its_id_belongs_to(db, monkeypatch, capsys):
    """The eight, and the arithmetic that says what they cost."""
    from payout.cli import retag_evs

    blive = _model_id(db, "Blive", "Standard")
    db.execute(
        "INSERT INTO ev_units (ev_id, model_id, status) VALUES ('CBICEVD0292', ?, 'in_use')",
        (blive,),
    )
    pid = make_person(db, "Jit Dey")
    from tests.conftest import assign

    assign(db, pid, "CBICEVD0292", handover="2026-09-14")
    for day in ("2026-09-15", "2026-09-16", "2026-09-17"):
        db.execute(
            "INSERT INTO ev_daily_ledger (ev_id, day, state, assigned_person_id, daily_cost, "
            "provider_cost, billing_status) VALUES (?,?, 'billable', ?, 18000, 18000, 'billed')",
            ("CBICEVD0292", day, pid),
        )
    db.commit()

    class Keep:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(retag_evs, "get_connection", lambda: Keep())

    assert retag_evs.main([]) == 0
    out = capsys.readouterr().out
    assert "Blive Standard" in out and "Raft Blue" in out
    assert "Jit Dey" in out
    assert "short" in out
    assert (
        int(
            db.execute("SELECT model_id FROM ev_units WHERE ev_id='CBICEVD0292'").fetchone()[
                "model_id"
            ]
        )
        == blive
    ), "the dry run moved it"

    assert retag_evs.main(["--apply"]) == 0
    row = db.execute(
        "SELECT m.provider, m.model_name FROM ev_units u JOIN ev_models m "
        "ON m.model_id=u.model_id WHERE u.ev_id='CBICEVD0292'"
    ).fetchone()
    assert (row["provider"], row["model_name"]) == ("Raft", "Blue")


def test_retag_leaves_the_ledger_alone(db, monkeypatch, capsys):
    """Rent already booked stays booked — the script reports the gap, it does
    not collect it."""
    from payout.cli import retag_evs

    db.execute(
        "INSERT INTO ev_units (ev_id, model_id, status) VALUES ('CBICEVD0293', ?, 'spare')",
        (_model_id(db, "Blive", "Standard"),),
    )
    db.execute(
        "INSERT INTO ev_daily_ledger (ev_id, day, state, daily_cost, provider_cost, "
        "billing_status) VALUES ('CBICEVD0293', '2026-09-15', 'billable', 18000, 18000, 'billed')"
    )
    db.commit()

    class Keep:
        def __enter__(self):
            return db

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(retag_evs, "get_connection", lambda: Keep())
    retag_evs.main(["--apply"])
    capsys.readouterr()
    assert (
        int(
            db.execute(
                "SELECT daily_cost FROM ev_daily_ledger WHERE ev_id='CBICEVD0293'"
            ).fetchone()["daily_cost"]
        )
        == 18000
    )
