"""Routes that exist for the recruiter app's first paint.

`GET /app/bootstrap` answers everything the app needs before it can draw a
useful screen — who I am, the companies and hubs for pickers, the size of
the roster and fleet — in one round trip. Nothing here is money.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from payout.api.auth import get_current_user
from payout.db import get_connection

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
        hubs = [
            r["hub"]
            for r in conn.execute(
                "SELECT DISTINCT hub FROM rider_master WHERE hub IS NOT NULL AND hub <> '' "
                "ORDER BY hub"
            )
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
    return {
        "api_version": APP_API_VERSION,
        "server_time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "me": {"email": user["email"], "role": user["role"], "phone": user.get("phone")},
        "companies": companies,
        "hubs": hubs,
        "ev_models": providers,
        "counts": {
            "rider_ids_active": int(riders_active),
            "persons_active": int(persons),
            "evs": evs,
        },
    }
