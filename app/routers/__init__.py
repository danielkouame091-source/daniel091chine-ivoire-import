"""Point d'entrée unique des routers."""
from app.routers import (
    admin_cockpit,
    ai,
    auth,
    billing,
    ecritures,
    freeze,
    journaux,
    mobile_money,
    plan_comptable,
    reporting,
    stock,
    tenants,
    users,
    whatsapp,
)

__all__ = [
    "admin_cockpit", "ai", "auth", "billing", "ecritures", "freeze",
    "journaux", "mobile_money", "plan_comptable", "reporting", "stock",
    "tenants", "users", "whatsapp",
]
