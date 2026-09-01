"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from payout.api.config import CORS_ORIGINS, DEMO_MODE
from payout.api.routes import (
    arrears as arrears_routes,
)
from payout.api.routes import (
    auth as auth_routes,
)
from payout.api.routes import (
    cod as cod_routes,
)
from payout.api.routes import (
    companies as company_routes,
)
from payout.api.routes import (
    creator as creator_routes,
)
from payout.api.routes import (
    cycle as cycle_routes,
)
from payout.api.routes import (
    dashboard as dashboard_routes,
)
from payout.api.routes import (
    ev_rent as ev_rent_routes,
)
from payout.api.routes import (
    evs as evs_routes,
)
from payout.api.routes import (
    inactive as inactive_routes,
)
from payout.api.routes import (
    ledger as ledger_routes,
)
from payout.api.routes import (
    payments as payments_routes,
)
from payout.api.routes import (
    persons as persons_routes,
)
from payout.api.routes import (
    providers as providers_routes,
)
from payout.api.routes import (
    riders as riders_routes,
)
from payout.api.routes import (
    users as users_routes,
)

# Path to the React production build (populated by `npm run build` in frontend/)
# __file__ = src/payout/api/app.py → parents[3] = project root
_FRONTEND_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"


_DEMO_EMAILS = ("admin@demo.com", "viewer@demo.com")


def _seed_demo_users() -> bool:
    """Create the demo accounts on an otherwise EMPTY user table.

    Refuses when any real (non-demo) user exists — a database with real users
    is a real deployment, whatever the environment says. Returns True if the
    accounts were created. Credentials (public, for the demo site only):
      admin@demo.com  /  Demo-1234  (role: admin)
      viewer@demo.com /  Demo-1234  (role: user)
    """
    from payout.auth import hash_password
    from payout.db import get_connection

    with get_connection() as conn:
        real = conn.execute(
            "SELECT COUNT(*) FROM users WHERE email NOT IN (?, ?)", _DEMO_EMAILS
        ).fetchone()[0]
        if real:
            print(
                "[startup] PAYOUT_SEED_DEMO is set but the users table already has "
                f"{real} real account(s) — refusing to create demo logins."
            )
            return False
        demo_users = [
            (_DEMO_EMAILS[0], hash_password("Demo-1234"), "admin"),
            (_DEMO_EMAILS[1], hash_password("Demo-1234"), "user"),
        ]
        for email, pw_hash, role in demo_users:
            conn.execute(
                "INSERT OR IGNORE INTO users (email, password_hash, role) VALUES (?,?,?)",
                (email, pw_hash, role),
            )
        conn.commit()
    print("[startup] Demo users ready: admin@demo.com / viewer@demo.com")
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB schema (+ demo data when PAYOUT_SEED_DEMO=1) before the first request."""
    from payout.db import get_connection, initialize_database
    from payout.db.demo_seed import seed_demo

    applied = initialize_database()
    if applied:
        print(f"[startup] applied migrations: {', '.join(applied)}")
    if DEMO_MODE:
        _seed_demo_users()
        with get_connection() as conn:
            seed_demo(conn)
    yield


app = FastAPI(
    title="Payout System API",
    description=(
        "HTTP API wrapping the payout engine - parses company files, applies rent "
        "(with handover proration and maintenance windows), settles arrears and "
        "general dues, handles COD holds, and produces the styled output workbook."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from payout.api.middleware import AuditLogMiddleware, RupeeizeMiddleware  # noqa: E402

app.add_middleware(AuditLogMiddleware)
app.add_middleware(RupeeizeMiddleware)

app.include_router(auth_routes.router, prefix="/api/auth", tags=["auth"])
app.include_router(company_routes.router, prefix="/api/companies", tags=["companies"])
app.include_router(cycle_routes.router, prefix="/api/cycles", tags=["cycles"])
app.include_router(riders_routes.router, prefix="/api/riders", tags=["riders"])
app.include_router(persons_routes.router, prefix="/api/persons", tags=["persons"])
app.include_router(evs_routes.router, prefix="/api/evs", tags=["evs"])
app.include_router(ledger_routes.router, prefix="/api/ledger", tags=["ledger"])
app.include_router(providers_routes.router, prefix="/api/providers", tags=["providers"])
app.include_router(arrears_routes.router, prefix="/api/arrears", tags=["arrears"])
app.include_router(inactive_routes.router, prefix="/api/inactive", tags=["inactive"])
app.include_router(cod_routes.router, prefix="/api/cod", tags=["cod"])
app.include_router(ev_rent_routes.router, prefix="/api/ev-rent", tags=["ev-rent"])
app.include_router(payments_routes.router, prefix="/api/payments", tags=["payments"])
app.include_router(dashboard_routes.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(users_routes.router, prefix="/api/users", tags=["users"])
app.include_router(creator_routes.router, prefix="/api/creator", tags=["creator"])


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    """Liveness probe. ``demo`` tells the SPA whether to offer the demo login."""
    return {"status": "ok", "demo": DEMO_MODE}


# ── Serve React SPA (production only — Vite dev server handles this in dev) ──
if _FRONTEND_DIR.exists():
    # Serve static assets (JS/CSS/images) under /assets and other static paths
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        """Catch-all: return index.html so React Router handles client-side routes.

        Unknown /api/* paths must NOT fall through to the SPA — a typo'd API call
        should be a 404 JSON, not a 200 with an HTML body.
        """
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found")
        index = _FRONTEND_DIR / "index.html"
        return FileResponse(str(index))
