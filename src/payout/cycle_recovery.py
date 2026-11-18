"""Read-only report for a cycle committed before workbook archiving."""

from io import BytesIO

from openpyxl import Workbook

from payout.exports import add_styled_sheet


def build_ledger_workbook(conn, company: str, cycle_start: str, cycle_end: str) -> BytesIO:
    """Use the stored cycle totals. Old transactions identify a window, not a run."""
    window = (company, cycle_start, cycle_end)
    cycle = conn.execute(
        "SELECT company, cycle_start, cycle_end, processed_at, rider_count, riders_paid, "
        "total_release, total_rent_charged FROM company_cycles "
        "WHERE company=? AND cycle_start=? AND cycle_end=?",
        window,
    ).fetchone()
    if cycle is None:
        raise ValueError("No committed cycle for this company and date range.")

    wb = Workbook()
    wb.remove(wb.active)
    add_styled_sheet(
        wb,
        sheet_name="Recorded cycle",
        headers=(
            "Company",
            "Cycle start",
            "Cycle end",
            "Processed at",
            "Riders",
            "Riders paid",
            "Net released (₹)",
            "Rent charged (₹)",
        ),
        rows=[tuple(cycle)],
        numeric_cols=(7, 8),
        money_cols=(7, 8),
    )
    ws = wb["Recorded cycle"]
    ws["A4"] = "The original workbook was not saved. These totals come from the committed cycle."
    ws["A5"] = "Window ledger lists every entry booked to this company and these exact dates."
    ws["A6"] = "It can include later adjustments or other runs booked to the same dates."
    ws["A7"] = "Use this report for reconciliation. It does not contain payment instructions."

    rows = conn.execute(
        "SELECT id, person_id, rider_id, event_type, amount, balance_after, days, "
        "remarks, created_at FROM reporting_transactions "
        "WHERE company=? AND cycle_start=? AND cycle_end=? "
        "ORDER BY id",
        window,
    ).fetchall()
    add_styled_sheet(
        wb,
        sheet_name="Window ledger",
        headers=(
            "Entry ID",
            "Person ID",
            "Rider ID",
            "Event",
            "Amount (₹)",
            "Balance after (₹)",
            "Days",
            "Remarks",
            "Recorded at",
        ),
        rows=[tuple(row) for row in rows],
        numeric_cols=(5, 6),
        money_cols=(5, 6),
        left_align_cols=(3, 4, 8),
    )
    # Rider IDs, company names and remarks are data, even if they start with '='.
    for sheet in wb:
        for row in sheet.iter_rows(min_row=2):
            for cell in row:
                if cell.data_type == "f":
                    cell.data_type = "s"
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf
