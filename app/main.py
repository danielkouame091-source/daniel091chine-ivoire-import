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
    admin_cockpit, ai, auth, billing, ecritures, freeze, journaux,
    mobile_money, plan_comptable, tenants, users, whatsapp,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    docs_url="/docs" if not settings.is_prod else None,
    redoc_url="/redoc" if not settings.is_prod else None,
    openapi_url="/openapi.json" if not settings.is_prod else None,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TenancyMiddleware)


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
app.include_router(ai.router,             prefix=f"{P}/ai",             tags=["ai"])
app.include_router(whatsapp.router,       prefix=f"{P}/whatsapp",       tags=["whatsapp"])
app.include_router(admin_cockpit.router,  prefix=f"{P}/cockpit",        tags=["cockpit"])


@app.get("/health", tags=["system"])
async def health() -> dict:
    return {
        "status": "ok",
        "env": settings.ENV,
        "app": settings.APP_NAME,
        "nlp_enabled": settings.nlp_enabled,
        "whatsapp_enabled": settings.whatsapp_enabled,
    }
# ... (identique à la brique 12) ...
from app.routers import (
    admin_cockpit, ai, auth, billing, ecritures, freeze, journaux,
    mobile_money, plan_comptable, reporting, tenants, users, whatsapp,
)

# ...from app.routers import (
    admin_cockpit, ai, auth, billing, ecritures, freeze, journaux,
    mobile_money, plan_comptable, reporting, stock, tenants, users, whatsapp,
)
# ...
app.include_router(stock.router,          prefix=f"{P}/stock",          tags=["stock"])

app.include_router(reporting.router,      prefix=f"{P}/reporting",      tags=["reporting"])
from app.routers import (
    admin_cockpit, ai, assets, auth, billing, ecritures, freeze, journaux,
    mobile_money, plan_comptable, reporting, stock, tenants, users, whatsapp,
)

# ...

app.include_router(assets.router,         prefix=f"{P}/assets",         tags=["assets"])
from app.routers import (
    admin_cockpit, ai, assets, auth, billing, ecritures, freeze, journaux,
    mobile_money, plan_comptable, purchases, reporting, stock, tenants, users, whatsapp,
)

# ...

app.include_router(purchases.router,      prefix=f"{P}/purchases",      tags=["purchases"])from app.routers import (
    admin_cockpit, ai, assets, auth, billing, ecritures, freeze, journaux,
    mobile_money, plan_comptable, purchases, reporting, sales, stock,
    tenants, users, whatsapp,
)

# ...

app.include_router(sales.router,          prefix=f"{P}/sales",          tags=["sales"])from app.routers import (
    admin_cockpit, ai, assets, auth, billing, ecritures, freeze, journaux,
    mobile_money, plan_comptable, purchases, reporting, sales, stock,
    tenants, treasury, users, whatsapp,
)

# ...

app.include_router(treasury.router,       prefix=f"{P}/treasury",       tags=["treasury"])
from app.routers import (
    admin_cockpit, ai, analytical, assets, auth, billing, ecritures, freeze,
    journaux, mobile_money, plan_comptable, purchases, reporting, sales,
    stock, tenants, treasury, users, whatsapp,
)

# ...

app.include_router(analytical.router,     prefix=f"{P}/analytical",     tags=["analytical"])from app.routers import (
    admin_cockpit, ai, analytical, assets, auth, billing, consolidation,
    ecritures, freeze, journaux, mobile_money, plan_comptable, purchases,
    reporting, sales, stock, tenants, treasury, users, whatsapp,
)

# ...

app.include_router(consolidation.router,  prefix=f"{P}/consolidation",  tags=["consolidation"])from app.routers import (
    admin_cockpit, ai, analytical, assets, auth, billing, consolidation,
    ecritures, fne, freeze, journaux, mobile_money, plan_comptable, purchases,
    reporting, sales, stock, tenants, treasury, users, whatsapp,
)

# ...

app.include_router(fne.router,            prefix=f"{P}/fne",            tags=["fne"])from app.middleware.audit_capture import AuditCaptureMiddleware

# Dans le bloc middlewares, APRÈS TenancyMiddleware :
app.add_middleware(AuditCaptureMiddleware)
from app.routers import (
    admin_cockpit, ai, analytical, assets, audit_internal, auth, billing,
    consolidation, ecritures, fne, freeze, journaux, mobile_money,
    plan_comptable, purchases, reporting, sales, stock, tenants, treasury,
    users, whatsapp,
)
from app.middleware.audit_capture import AuditCaptureMiddleware

# Dans les middlewares :
app.add_middleware(TenancyMiddleware)
app.add_middleware(AuditCaptureMiddleware)

# Dans les routers :
app.include_router(audit_internal.router, prefix=f"{P}/audit",           tags=["audit"])
from app.routers import (
    admin_cockpit, ai, analytical, assets, audit_internal, auth, billing,
    consolidation, ecritures, fne, formation, freeze, journaux, mobile_money,
    plan_comptable, projects, purchases, reporting, sales, stock, tenants,
    treasury, users, whatsapp,
)

# ...

app.include_router(formation.router,      prefix=f"{P}/formation",      tags=["formation"])
from app.routers import (
    admin_cockpit, ai, analytical, assets, audit_internal, auth, billing,
    consolidation, ecritures, fne, formation, freeze, hr, journaux,
    mobile_money, plan_comptable, portal, projects, purchases, reporting,
    sales, stock, tenants, treasury, users, whatsapp,
)

# ...

app.include_router(hr.router,             prefix=f"{P}/hr",             tags=["hr"])
from app.routers import (
    admin_cockpit, ai, analytical, assets, audit_internal, auth, billing,
    consolidation, ecritures, fne, formation, freeze, hr, journaux,
    mobile_money, notifications, plan_comptable, portal, projects, purchases,
    reporting, sales, stock, tenants, treasury, users, whatsapp,
)

# ...

app.include_router(notifications.router,  prefix=f"{P}/notifications",  tags=["notifications"])
from app.routers import (
    admin_cockpit, ai, analytical, assets, audit_internal, auth, bi, billing,
    consolidation, ecritures, fne, formation, freeze, hr, journaux,
    mobile_money, notifications, plan_comptable, portal, projects, purchases,
    public_api, public_api_admin, reporting, sales, stock, tenants, treasury,
    users, whatsapp,
)
from app.middleware.public_api_auth import PublicApiAuthMiddleware

# Middlewares (ordre critique)
app.add_middleware(CORSMiddleware, ...)
app.add_middleware(TenancyMiddleware)
app.add_middleware(AuditCaptureMiddleware)
app.add_middleware(PublicApiAuthMiddleware)   # ⚠️ AVANT les routers

# Routers
app.include_router(public_api.router,       prefix=f"{P}/public",       tags=["public-api"])
app.include_router(public_api_admin.router, prefix=f"{P}/api-admin",    tags=["api-admin"])
from app.routers import (
    admin_cockpit, ai, analytical, assets, audit_internal, auth, bi, billing,
    consolidation, ecritures, fne, formation, freeze, ged, hr, journaux,
    mobile_money, notifications, plan_comptable, portal, projects, purchases,
    public_api, public_api_admin, reporting, sales, stock, tenants, treasury,
    users, whatsapp,
)

# ...

app.include_router(ged.router,            prefix=f"{P}/ged",            tags=["ged"])
from app.routers import (
    admin_cockpit, ai, analytical, assets, audit_internal, auth, bi, billing,
    consolidation, ecritures, fne, formation, freeze, ged, hr, journaux,
    mobile_money, notifications, plan_comptable, portal, privacy, projects,
    purchases, public_api, public_api_admin, reporting, sales, stock, tenants,
    treasury, users, whatsapp,
)

# ...

app.include_router(privacy.router,        prefix=f"{P}/privacy",        tags=["privacy"])
from app.routers import (
    admin_cockpit, ai, analytical, assets, audit_internal, auth, bi, billing,
    consolidation, developer, ecritures, fne, formation, freeze, ged, hr,
    journaux, marketplace, marketplace_admin, mobile_money, notifications,
    plan_comptable, portal, privacy, projects, purchases, public_api,
    public_api_admin, realtime, reporting, sales, stock, tenants, treasury,
    users, whatsapp,
)

# ...

app.include_router(realtime.router,       prefix=f"{P}/realtime",       tags=["realtime"])
from app.routers import chatbot
# ...
app.include_router(chatbot.router, prefix=f"{P}/chatbot", tags=["chatbot"])
