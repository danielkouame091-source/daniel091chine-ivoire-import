"""Point d'entrée unique des routers."""
from app.routers import (
    admin_cockpit, ai, analytical, assets, audit_internal, auth, billing,
    consolidation, ecritures, fne, formation, freeze, hr, journaux,
    mobile_money, plan_comptable, portal, projects, purchases, reporting,
    sales, stock, tenants, treasury, users, whatsapp,
)

__all__ = [
    "admin_cockpit", "ai", "analytical", "assets", "audit_internal", "auth",
    "billing", "consolidation", "ecritures", "fne", "formation", "freeze",
    "hr", "journaux", "mobile_money", "plan_comptable", "portal", "projects",
    "purchases", "reporting", "sales", "stock", "tenants", "treasury",
    "users", "whatsapp",
]
