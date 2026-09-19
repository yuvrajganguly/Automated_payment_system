"""The things that cannot be true — one page of them.

Every problem this system has had in September 2026 was found the same way:
a number on a report looked wrong, somebody asked, and a query written by hand
turned up a contradiction that had been sitting in the database for weeks. The
contradiction was always findable on day one. Nobody was looking, because
there was nowhere to look.

See ``domain.anomalies`` for what counts as a finding and what does not.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from payout.api.auth import require_admin
from payout.db import get_connection
from payout.domain.anomalies import CHECKS, run_checks

router = APIRouter()


@router.get("")
def list_anomalies(_: dict = Depends(require_admin)) -> dict:
    """Every check, worst first, with a count by severity for the header.

    Computed on the way in rather than cached: the whole point is that it is
    true right now, and a stale "all clear" is worse than no page at all. The
    checks read a few thousand rows between them, which on this data is well
    under a second.
    """
    with get_connection() as conn:
        findings = run_checks(conn)
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["severity"]] = counts.get(f["severity"], 0) + 1
    return {
        "findings": findings,
        "counts": counts,
        "total": len(findings),
        "checks_run": len(CHECKS),
    }
