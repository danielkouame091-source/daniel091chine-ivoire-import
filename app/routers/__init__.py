"""Point d'entrée unique des routers."""
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

__all__ = [
    "admin_cockpit",
    "auth",
    "billing",
    "ecritures",
    "freeze",
    "journaux",
    "mobile_money",
    "plan_comptable",
    "tenants",
    "users",
]
