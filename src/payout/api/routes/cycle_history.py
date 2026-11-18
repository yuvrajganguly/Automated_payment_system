"""Read a processed payout without running its settlement again."""

from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response

from payout.api.auth import require_admin
from payout.db import get_connection
from payout.exports import XLSX_MIME, build_xlsx

router = APIRouter(prefix="/history")


@router.get("")
def history(company: str | None = None, _: dict = Depends(require_admin)) -> dict:
    # Keep the workbook bytes out of list queries. Older runs have their
    # original metadata but no matching workbook snapshot.
    query = """
        SELECT c.id, 'cycle' AS kind, c.company, c.cycle_start, c.cycle_end,
               NULL AS label, c.processed_at,
               CASE WHEN w.cycle_id IS NULL THEN 'ledger' ELSE 'original' END AS report
        FROM company_cycles c LEFT JOIN payout_workbooks w ON w.cycle_id=c.id
        UNION ALL
        SELECT a.id, 'ad_hoc', a.company, w.cycle_start, a.ran_on, a.label, a.created_at,
               CASE WHEN w.adhoc_id IS NULL THEN 'summary' ELSE 'original' END
        FROM adhoc_runs a LEFT JOIN payout_workbooks w ON w.adhoc_id=a.id
    """
    params = ()
    if company is not None:
        query = f"SELECT * FROM ({query}) AS runs WHERE company=?"
        params = (company,)
    with get_connection() as conn:
        rows = conn.execute(query + " ORDER BY processed_at DESC, id DESC, kind", params)
        return {"runs": [dict(row) for row in rows]}


@router.get("/{kind}/{run_id}/download")
def download_run(
    kind: Literal["cycle", "ad_hoc"], run_id: int, _: dict = Depends(require_admin)
) -> Response:
    with get_connection() as conn:
        owner = "cycle_id" if kind == "cycle" else "adhoc_id"
        saved = conn.execute(
            f"SELECT filename, content FROM payout_workbooks WHERE {owner}=?", (run_id,)
        ).fetchone()
        if saved:
            filename, content = saved["filename"], saved["content"]
        elif kind == "cycle":
            from payout.cycle_recovery import build_ledger_workbook

            cycle = conn.execute(
                "SELECT company, cycle_start, cycle_end FROM company_cycles WHERE id=?", (run_id,)
            ).fetchone()
            if cycle is None:
                raise HTTPException(404, "Payout run not found")
            content = build_ledger_workbook(
                conn, cycle["company"], cycle["cycle_start"], cycle["cycle_end"]
            ).getvalue()
            filename = f"payout_ledger_{cycle['company']}_{cycle['cycle_end']}_{run_id}.xlsx"
        else:
            run = conn.execute(
                "SELECT id, company, ran_on, label, riders, total_paid, created_at "
                "FROM adhoc_runs WHERE id=?",
                (run_id,),
            ).fetchone()
            if run is None:
                raise HTTPException(404, "Payout run not found")
            # Multiple ad-hoc runs may share a company and date. Old ledger
            # entries cannot be attached to an individual file with certainty.
            content = build_xlsx(
                sheet_name="Ad-hoc run summary",
                headers=(
                    "Run ID",
                    "Company",
                    "Run date",
                    "Label",
                    "Riders in file",
                    "Gross in file (INR)",
                    "Processed at",
                ),
                rows=[
                    tuple("'" + v if isinstance(v, str) and v.startswith("=") else v for v in run)
                ],
                money_cols=(6,),
                numeric_cols=(6,),
            ).getvalue()
            filename = f"payout_summary_{run['company']}_{run['ran_on']}_{run_id}.xlsx"
    return Response(
        content=content,
        media_type=XLSX_MIME,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename, safe='')}",
            "Cache-Control": "no-store",
        },
    )
