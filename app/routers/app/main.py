"""Point d'entrée FastAPI — assemble middlewares, routers et handlers."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

from app.core.config import settings
from app.core.exceptions import DomainError
from app.db.session import engine
from app.middleware.tenancy import TenancyMiddleware
from app.routers import (
    admin_cockpit,
    auth,
    billing,
    ecritures,
    freeze,
    journaux,
    mobile_money,
    plan_comptable,
    tenants,
    users,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup : rien de bloquant (les migrations sont gérées par Alembic)
    yield
    # Shutdown : fermer proprement le pool
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url="/docs" if not settings.is_prod else None,
    redoc_url="/redoc" if not settings.is_prod else None,
    openapi_url="/openapi.json" if not settings.is_prod else None,
    lifespan=lifespan,
)


# ---------------------------------------------------------------------
# Middlewares (ordre critique)
# ---------------------------------------------------------------------
# 1. CORS en premier (préflight sans auth)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2. Tenancy : pose tenant_id / read_only / frozen dans request.state
app.add_middleware(TenancyMiddleware)


# ---------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------
@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=exc.detail)


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": "VALIDATION_ERROR",
            "message": "Payload invalide",
            "details": exc.errors(),
        },
    )


# ---------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------
P = settings.API_PREFIX

app.include_router(auth.router,           prefix=f"{P}/auth",           tags=["auth"])
app.include_router(tenants.router,        prefix=f"{P}/tenants",        tags=["tenants"])
app.include_router(users.router,          prefix=f"{P}/users",          tags=["users"])
app.include_router(plan_comptable.router, prefix=f"{P}/plan-comptable", tags=["syscohada"])
app.include_router(journaux.router,       prefix=f"{P}/journaux",       tags=["syscohada"])
app.include_router(ecritures.router,      prefix=f"{P}/ecritures",      tags=["syscohada"])
app.include_router(mobile_money.router,   prefix=P,                     tags=["mobile-money"])
app.include_router(freeze.router,         prefix=f"{P}/freeze",         tags=["freeze"])
app.include_router(billing.router,        prefix=f"{P}/billing",        tags=["billing"])
app.include_router(admin_cockpit.router,  prefix=f"{P}/cockpit",        tags=["cockpit"])


# ---------------------------------------------------------------------
# Santé
# ---------------------------------------------------------------------
@app.get("/health", tags=["system"])
async def health() -> dict:
    return {"status": "ok", "env": settings.ENV, "app": settings.APP_NAME}
