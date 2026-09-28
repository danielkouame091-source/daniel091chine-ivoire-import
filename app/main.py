from fastapi import FastAPI
from app.core.config import settings
from app.middleware.tenancy import TenancyMiddleware
from app.middleware.audit import AuditMiddleware
from app.routers import (
    auth, ecritures, plan_comptable, journaux, mobile_money,
    freeze, nlp, billing, admin_cockpit, tenants, users,
)

app = FastAPI(title="MTech SaaS SYSCOHADA", version="0.1.0")

app.add_middleware(TenancyMiddleware)
app.add_middleware(AuditMiddleware)

API = "/api/v1"
app.include_router(auth.router,            prefix=f"{API}/auth",            tags=["auth"])
app.include_router(tenants.router,         prefix=f"{API}/tenants",         tags=["tenants"])
app.include_router(users.router,           prefix=f"{API}/users",           tags=["users"])
app.include_router(plan_comptable.router,  prefix=f"{API}/plan-comptable",  tags=["syscohada"])
app.include_router(journaux.router,        prefix=f"{API}/journaux",        tags=["syscohada"])
app.include_router(ecritures.router,       prefix=f"{API}/ecritures",       tags=["syscohada"])
app.include_router(mobile_money.router,    prefix=f"{API}",                 tags=["mobile-money"])
app.include_router(freeze.router,          prefix=f"{API}/freeze",          tags=["freeze"])
app.include_router(nlp.router,             prefix=f"{API}/ai",              tags=["ai"])
app.include_router(billing.router,         prefix=f"{API}/billing",         tags=["billing"])
app.include_router(admin_cockpit.router,   prefix=f"{API}/cockpit",         tags=["cockpit"])

@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.ENV}
