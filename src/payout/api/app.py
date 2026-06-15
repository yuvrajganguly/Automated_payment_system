"""FastAPI application entry point."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

app = FastAPI(
    title="Payout System API",
    description=(
        "HTTP API wrapping the payout engine - parses company files, applies rent "
        "(with handover proration and maintenance windows), settles arrears and "
        "general dues, handles COD holds, and produces the styled output workbook."
    ),
    version="0.1.0",
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
