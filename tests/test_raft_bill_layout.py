"""Reading Raft's weekly bill as Raft actually sends it (W38, 2026).

The sheet opens with a merged banner — "WEEK W38 (2026) (14th September to
20th September)" — and then a header row that calls the unit a **Tracker No**
and the money a **Deduction**, with notes split across **Remarks 1** and
**Remarks 2**. None of those were names the parser knew, and the banner became
the header, so the upload failed with an error listing one column that was the
title of the document.

Every row below is copied from the real W38 file.
"""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook

from payout.api.routes.providers import _parse_bill_excel

# Sr. / Deployment Date / Tracker No / VIN No / DP Name / Deduction / Remarks 1 / Remarks 2
W38 = [
    [1, "18-Apr-25", "EV1601", "RCEV/K1/00269", "BUDDHADEV GHOSH", 1050, "", ""],
    [10, "08-Dec-25", "CBICEVD0185", "RCEV/K1/01437", "BITTU MAHANTI", 1225, "", ""],
    [
        18,
        "14-Apr-26",
        "CBICEVD0022",
        "RCEV/M1/00826",
        "ABHIJIT DAS",
        1050,
        "LESS 1 DAY UNDER MAINTENANCE",
        "EV HOLD FOR MAINTENANCE",
    ],
    [
        58,
        "13-Aug-26",
        "CBICEVD0110",
        "RCEV/K1/01314",
        "ANAND SHAW",
        0,
        "RETURN DT:- 14-09-2026",
        "",
    ],
    [
        61,
        "19-Sep-26",
        "CBICEVD0056",
        "RCEV/M1/00885",
        "ROHIT CHOWDHURY",
        1610,
        "DAMAGE CHARGES",
        "",
    ],
    [86, "12-Sep-26", "CBICEVD0292", "RCEV/K1/01548", "JIT DEY", 1225, "", ""],
    [90, "15-Sep-26", "CBICEVD0296", "RCEV/K1/01539", "RAJDEEP MONDAL", 875, "", ""],
]


def _sheet(rows, banner=True):
    wb = Workbook()
    ws = wb.active
    if banner:
        ws.append(["WEEK W38 (2026) (14th September to 20th September)"])
    ws.append(
        [
            "Sr.",
            "Deployment Date",
            "Tracker No",
            "VIN No",
            "DP Name",
            "Deduction",
            "Remarks 1",
            "Remarks 2",
        ]
    )
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_the_banner_row_is_not_mistaken_for_the_header():
    lines = _parse_bill_excel(_sheet(W38), "raft_w38.xlsx")
    assert len(lines) == len(W38)


def test_tracker_no_is_the_ev_id_and_deduction_is_the_money():
    lines = _parse_bill_excel(_sheet(W38), "raft_w38.xlsx")
    by_ev = {L["ev_id"]: L for L in lines}
    assert by_ev["CBICEVD0292"]["their_amount"] == 122500  # paise
    assert by_ev["CBICEVD0296"]["their_amount"] == 87500  # five days, not a full week


def test_the_rider_name_the_provider_has_comes_through():
    """It is how a unit we renamed is still recognised, and how a disagreement
    about who holds a vehicle surfaces at all."""
    by_ev = {L["ev_id"]: L for L in _parse_bill_excel(_sheet(W38), "w38.xlsx")}
    assert by_ev["CBICEVD0292"]["provider_name"] == "JIT DEY"
    assert by_ev["CBICEVD0292"]["vin"] == "RCEV/K1/01548"
    assert by_ev["CBICEVD0292"]["deploy_date"] == "12-Sep-26"


def test_both_remarks_columns_survive():
    """The damage charge is in one and the maintenance hold in the other.
    Taking a single column dropped whichever half the heuristic missed."""
    by_ev = {L["ev_id"]: L for L in _parse_bill_excel(_sheet(W38), "w38.xlsx")}
    note = by_ev["CBICEVD0022"]["status_note"]
    assert "LESS 1 DAY UNDER MAINTENANCE" in note
    assert "EV HOLD FOR MAINTENANCE" in note
    assert by_ev["CBICEVD0110"]["status_note"] == "RETURN DT:- 14-09-2026"


def test_a_zero_line_is_kept():
    """A returned vehicle billed at zero still has to appear, or the count of
    what they think we hold silently disagrees with ours."""
    lines = _parse_bill_excel(_sheet(W38), "w38.xlsx")
    zero = [L for L in lines if L["ev_id"] == "CBICEVD0110"]
    assert zero and zero[0]["their_amount"] == 0


def test_the_same_tracker_can_appear_twice():
    """Rent on one line and a damage charge on another — W38 does this for
    three vehicles."""
    rows = [
        *W38,
        [62, "19-Sep-26", "CBICEVD0292", "RCEV/K1/01548", "JIT DEY", 360, "DAMAGE CHARGES", ""],
    ]
    lines = _parse_bill_excel(_sheet(rows), "w38.xlsx")
    mine = [L for L in lines if L["ev_id"] == "CBICEVD0292"]
    assert len(mine) == 2
    assert sorted(L["their_amount"] for L in mine) == [36000, 122500]


def test_the_bill_total_matches_the_sheet():
    """W38 foots to 100,710. The sample here is a subset; what matters is that
    the parser's sum is the sum of the column and nothing is dropped."""
    lines = _parse_bill_excel(_sheet(W38), "w38.xlsx")
    assert sum(L["their_amount"] for L in lines) == sum(r[5] for r in W38) * 100


def test_a_sheet_with_no_banner_still_works():
    """Blive send theirs without one."""
    assert len(_parse_bill_excel(_sheet(W38, banner=False), "w38.xlsx")) == len(W38)


def test_a_file_with_neither_column_says_so_usefully():
    wb = Workbook()
    ws = wb.active
    ws.append(["something", "else"])
    ws.append(["a", "b"])
    buf = io.BytesIO()
    wb.save(buf)
    with pytest.raises(Exception) as e:
        _parse_bill_excel(buf.getvalue(), "wrong.xlsx")
    assert "columns" in str(e.value).lower()
