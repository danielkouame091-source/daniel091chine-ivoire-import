"""
Point d'entrée unique des modèles SQLAlchemy.
⚠️ TOUT nouveau modèle DOIT être importé ici, sinon Alembic autogenerate
ne le détecte pas et ne crée pas la migration.
"""
from app.models.audit import AuditLog
from app.models.ecriture import Ecriture, EcritureLigne
from app.models.exercice import Exercice
from app.models.freeze import (
    FreezeCascadeRule,
    FreezeEvent,
    FreezeTarget,
    TenantFreezeState,
)
from app.models.journal import Journal
from app.models.mobile_money import MmTransaction
from app.models.plan import Plan
from app.models.plan_comptable import PlanComptable
from app.models.session import Session
from app.models.subscription import Subscription, SubscriptionPayment
from app.models.tenant import Tenant
from app.models.user import User

__all__ = [
    "AuditLog",
    "Ecriture",
    "EcritureLigne",
    "Exercice",
    "FreezeCascadeRule",
    "FreezeEvent",
    "FreezeTarget",
    "Journal",
    "MmTransaction",
    "Plan",
    "PlanComptable",
    "Session",
    "Subscription",
    "SubscriptionPayment",
    "Tenant",
    "TenantFreezeState",
    "User",
]
