"""Point d'entrée unique des routers."""
from app.routers import (
    admin_cockpit, ai, analytical, assets, audit_internal, auth, bi, billing,
    consolidation, ecritures, fne, formation, freeze, hr, journaux,
    mobile_money, notifications, plan_comptable, portal, projects, purchases,
    public_api, public_api_admin, reporting, sales, stock, tenants, treasury,
    users, whatsapp,
)

__all__ = [
    "admin_cockpit", "ai", "analytical", "assets", "audit_internal", "auth",
    "bi", "billing", "consolidation", "ecritures", "fne", "formation",
    "freeze", "hr", "journaux", "mobile_money", "notifications",
    "plan_comptable", "portal", "projects", "purchases", "public_api",
    "public_api_admin", "reporting", "sales", "stock", "tenants", "treasury",
    "users", "whatsapp",
]
