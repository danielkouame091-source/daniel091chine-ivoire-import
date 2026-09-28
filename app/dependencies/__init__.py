"""Point d'entrée unique des dépendances FastAPI."""
from app.dependencies.auth import (
    CurrentUser,
    RequireAdminTenant,
    RequireAuditeur,
    RequireComptable,
    get_current_user,
    require_role,
)
from app.dependencies.founder import FounderUser, require_founder
from app.dependencies.subscription import (
    READ_ONLY_EXEMPT_PREFIXES,
    RequireActiveSubscription,
    SubscriptionStatus,
    get_subscription_status,
    require_active_subscription,
)
from app.dependencies.tenant import CurrentTenant, get_current_tenant
from app.dependencies.tenant_db import TenantDBSession

__all__ = [
    # auth
    "CurrentUser", "RequireAdminTenant", "RequireAuditeur", "RequireComptable",
    "get_current_user", "require_role",
    # founder
    "FounderUser", "require_founder",
    # tenant
    "CurrentTenant", "get_current_tenant",
    # tenant DB
    "TenantDBSession",
    # subscription
    "READ_ONLY_EXEMPT_PREFIXES", "RequireActiveSubscription", "SubscriptionStatus",
    "get_subscription_status", "require_active_subscription",
]
