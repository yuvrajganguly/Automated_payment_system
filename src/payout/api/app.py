"""FastAPI application entry point."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from payout.api.config import CORS_ORIGINS
from payout.api.routes import (
    arrears as arrears_routes,
    auth as auth_routes,
    cod as cod_routes,
    companies as company_routes,
    cycle as cycle_routes,
    ev_rent as ev_rent_routes,
    evs as evs_routes,
    inactive as inactive_routes,
    ledger as ledger_routes,
    persons as persons_routes,
    riders as riders_routes,
)

# Path to the React production build (populated by `npm run build` in frontend/)
_FRONTEND_DIR = Path(__file__).resolve().parents[4] / "frontend" / "dist"


def _seed_demo_users() -> None:
    """Create demo accounts if they don't already exist.

    Credentials (printed to stdout for Render logs):
      admin@demo.com  /  Demo@1234  (role: admin)
      viewer@demo.com /  Demo@1234  (role: user)
    """
    from payout.auth import hash_password
    from payout.db import get_connection

    demo_users = [
        ("admin@demo.com",  hash_password("Demo-1234"), "admin"),
        ("viewer@demo.com", hash_password("Demo-1234"), "user"),
    ]
    with get_connection() as conn:
        for email, pw_hash, role in demo_users:
            conn.execute(
                "INSERT OR IGNORE INTO users (email, password_hash, role) VALUES (?,?,?)",
                (email, pw_hash, role),
            )
        conn.commit()
    print("[startup] Demo users ready: admin@demo.com / viewer@demo.com  (pw: Demo@1234)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize DB schema + demo data before the first request."""
    from payout.db import initialize_database
    initialize_database()
    _seed_demo_users()
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

app.include_router(auth_routes.router,    prefix="/api/auth",      tags=["auth"])
app.include_router(company_routes.router, prefix="/api/companies", tags=["companies"])
app.include_router(cycle_routes.router,   prefix="/api/cycles",    tags=["cycles"])
app.include_router(riders_routes.router,  prefix="/api/riders",    tags=["riders"])
app.include_router(persons_routes.router, prefix="/api/persons",   tags=["persons"])
app.include_router(evs_routes.router,     prefix="/api/evs",       tags=["evs"])
app.include_router(ledger_routes.router,  prefix="/api/ledger",    tags=["ledger"])
app.include_router(arrears_routes.router, prefix="/api/arrears",   tags=["arrears"])
app.include_router(inactive_routes.router, prefix="/api/inactive", tags=["inactive"])
app.include_router(cod_routes.router,     prefix="/api/cod",       tags=["cod"])
app.include_router(ev_rent_routes.router, prefix="/api/ev-rent",   tags=["ev-rent"])


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok"}


# ── Serve React SPA (production only — Vite dev server handles this in dev) ──
if _FRONTEND_DIR.exists():
    # Serve static assets (JS/CSS/images) under /assets and other static paths
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_spa(full_path: str):
        """Catch-all: return index.html so React Router handles client-side routes."""
        index = _FRONTEND_DIR / "index.html"
        return FileResponse(str(index))
