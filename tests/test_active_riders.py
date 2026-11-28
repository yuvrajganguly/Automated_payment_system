"""Active riders = the riders in each company's own last payout."""

from __future__ import annotations

import io
from datetime import date

from openpyxl import Workbook

from payout.domain.engine import process_cycle
from tests.conftest import make_person, make_rider
from tests.test_rent_due import _hdr, client  # noqa: F401  (fixture)


def _file(rows) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(["rider_id", "rider_name", "hub", "total_del", "net_pay"])
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_only_the_riders_in_each_companys_last_payout(db, client):  # noqa: F811
    a = make_person(db, "Asha", balance=0)
    b = make_person(db, "Bilal", balance=0)
    make_rider(db, a, "70001", "Kaptan", "Asha")
    make_rider(db, b, "70002", "Kaptan", "Bilal")
    db.commit()
    # week 1: both rode; week 2: only Asha
    process_cycle(
        "Kaptan",
        date(2026, 11, 2),
        date(2026, 11, 8),
        _file([["70001", "Asha", "H1", 5, 900], ["70002", "Bilal", "H1", 5, 700]]),
        commit=True,
    )
    process_cycle(
        "Kaptan",
        date(2026, 11, 9),
        date(2026, 11, 15),
        _file([["70001", "Asha", "H1", 5, 1000]]),
        commit=True,
    )
    h = _hdr(client)
    r = client.get("/api/riders/active", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    (kap,) = [c for c in body["companies"] if c["company"] == "Kaptan"]
    assert (kap["cycle_end"], kap["riders"]) == ("2026-11-15", 1)
    ids = [x["rider_id"] for x in body["riders"] if x["company"] == "Kaptan"]
    assert ids == ["70001"]
    assert body["riders"][0]["payout"] == 1000.0
    only = client.get("/api/riders/active", params={"company": "Kaptan"}, headers=h).json()
    assert [c["company"] for c in only["companies"]] == ["Kaptan"]
