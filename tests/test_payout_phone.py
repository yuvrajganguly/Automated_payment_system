"""The rider's phone, from the payout file to the roster and the payout sheet.

Myntra's sheets carry each rider's phone under whatever heading the export
used that week — "Phone no", "Mobile No.", a number cell Excel turned into
9876543210.0. The roster (and so the recruiter app) should pick it up without
anybody typing it, and the PAY sheet should show it.
"""

from __future__ import annotations

import io
from datetime import date, timedelta

import pytest
from openpyxl import Workbook, load_workbook

from payout.domain.engine import process_cycle
from payout.parsers.generic import _phone
from tests.conftest import make_person, make_rider

WEEK = date.today() - timedelta(days=date.today().weekday(), weeks=1)


def _file(rows, headers):
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _phone_of(db, rid):
    return db.execute("SELECT mob_no FROM rider_master WHERE rider_id=?", (rid,)).fetchone()[0]


@pytest.mark.parametrize(
    "raw, want",
    [
        (9876543210.0, "9876543210"),
        ("+91 98765 43210", "9876543210"),
        ("098765-43210", "9876543210"),
        ("12345", None),
        ("n/a", None),
        (None, None),
    ],
)
def test_phone_cells_are_read_as_ten_digits(raw, want):
    assert _phone(raw) == want


@pytest.mark.parametrize(
    "header", ["Phone no", "phone no", "Mobile No.", "mobile no", "Contact No"]
)
def test_roster_phone_is_filled_from_the_file(db, header):
    pid = make_person(db, "Rana Das", balance=0, arrears=0)
    make_rider(db, pid, "MYN001", "Kaptan", "Rana Das")
    db.commit()
    res = process_cycle(
        "Kaptan",
        WEEK,
        WEEK + timedelta(days=6),
        _file([("MYN001", 4000, 9876543210.0)], ("rider_id", "net_pay", header)),
        commit=True,
    )
    assert _phone_of(db, "MYN001") == "9876543210"
    assert any(u["rider_id"] == "MYN001" for u in res.phone_updates)
    row = next(r for r in res.pay_rows + res.dues_rows if r.rider_id == "MYN001")
    assert row.mob_no == "9876543210"


def test_a_phone_belonging_to_someone_else_is_not_copied(db):
    a = make_person(db, "First", balance=0, arrears=0)
    make_rider(db, a, "MYN010", "Kaptan", "First")
    b = make_person(db, "Second", balance=0, arrears=0)
    make_rider(db, b, "MYN011", "Kaptan", "Second")
    db.execute("UPDATE rider_master SET mob_no='9000000001' WHERE rider_id='MYN010'")
    db.commit()
    res = process_cycle(
        "Kaptan",
        WEEK,
        WEEK + timedelta(days=6),
        _file(
            [("MYN010", 1000, "9000000001"), ("MYN011", 1000, "9000000001")],
            ("rider_id", "net_pay", "Phone no"),
        ),
        commit=True,
    )
    assert not _phone_of(db, "MYN011")
    assert any("already on person" in w for w in res.warnings)


def test_pay_sheet_has_a_mobile_column(db):
    from payout import output

    pid = make_person(db, "Rana Das", balance=0, arrears=0)
    make_rider(db, pid, "MYN001", "Kaptan", "Rana Das")
    db.commit()
    res = process_cycle(
        "Kaptan",
        WEEK,
        WEEK + timedelta(days=6),
        _file([("MYN001", 4000, "9876543210")], ("rider_id", "net_pay", "Phone no")),
        commit=False,
    )
    ws = load_workbook(output.build_output(res, db))["PAY"]
    headers = [c.value for c in ws[1]]
    col = headers.index("Mobile No") + 1
    assert ws.cell(row=2, column=col).value == "9876543210"
