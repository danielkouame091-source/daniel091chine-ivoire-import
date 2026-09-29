"""Point d'entrée unique des routers."""
from app.routers import (
    admin_cockpit, ai, analytical, assets, auth, billing, consolidation,
    ecritures, fne, freeze, journaux, mobile_money, plan_comptable, purchases,
    reporting, sales, stock, tenants, treasury, users, whatsapp,
)

__all__ = [
    "admin_cockpit", "ai", "analytical", "assets", "auth", "billing",
    "consolidation", "ecritures", "fne", "freeze", "journaux", "mobile_money",
    "plan_comptable", "purchases", "reporting", "sales", "stock",
    "tenants", "treasury", "users", "whatsapp",
]
