"""Point d'entrée unique des schémas Pydantic."""
from app.schemas.auth import (
    ChangePasswordIn,
    CurrentUserOut,
    LoginIn,
    MfaSetupOut,
    MfaVerifyIn,
    RefreshIn,
    TokenOut,
)
from app.schemas.common import (
    ApiError,
    ApiResponse,
    MontantXOF,
    ORMModel,
    Page,
    PaginationParams,
    TimestampedOut,
)
from app.schemas.ecriture import (
    EcritureBrief,
    EcritureCreate,
    EcritureFilter,
    EcritureOut,
    EcritureUpdate,
    LigneIn,
    LigneOut,
)
from app.schemas.exercice import ExerciceCreate, ExerciceOut
from app.schemas.freeze import (
    FreezeCascadeRuleOut,
    FreezeEventOut,
    FreezeRequest,
    FreezeResultOut,
    FreezeTargetOut,
    TenantFreezeStateOut,
    UnfreezeRequest,
)
from app.schemas.journal import JournalCreate, JournalOut, JournalUpdate
from app.schemas.mobile_money import (
    MmRapprochementIn,
    MmTransactionOut,
    MtnMomoWebhookPayload,
    OrangeMoneyWebhookPayload,
    WaveWebhookPayload,
)
from app.schemas.plan_comptable import (
    PlanComptableCreate,
    PlanComptableImportRow,
    PlanComptableOut,
    PlanComptableUpdate,
)
from app.schemas.subscription import (
    PlanOut,
    SubscriptionCreate,
    SubscriptionOut,
    SubscriptionPaymentOut,
    SubscriptionRenewIn,
    SubscriptionStatusOut,
)
from app.schemas.tenant import (
    AdresseIn,
    TenantBrief,
    TenantCreate,
    TenantOut,
    TenantUpdate,
)
from app.schemas.user import (
    UserBrief,
    UserCreate,
    UserInviteIn,
    UserOut,
    UserUpdate,
)

__all__ = [
    # common
    "ApiError", "ApiResponse", "MontantXOF", "ORMModel", "Page",
    "PaginationParams", "TimestampedOut",
    # auth
    "ChangePasswordIn", "CurrentUserOut", "LoginIn", "MfaSetupOut",
    "MfaVerifyIn", "RefreshIn", "TokenOut",
    # tenant
    "AdresseIn", "TenantBrief", "TenantCreate", "TenantOut", "TenantUpdate",
    # user
    "UserBrief", "UserCreate", "UserInviteIn", "UserOut", "UserUpdate",
    # subscription
    "PlanOut", "SubscriptionCreate", "SubscriptionOut", "SubscriptionPaymentOut",
    "SubscriptionRenewIn", "SubscriptionStatusOut",
    # exercice
    "ExerciceCreate", "ExerciceOut",
    # plan comptable
    "PlanComptableCreate", "PlanComptableImportRow", "PlanComptableOut",
    "PlanComptableUpdate",
    # journal
    "JournalCreate", "JournalOut", "JournalUpdate",
    # ecriture
    "EcritureBrief", "EcritureCreate", "EcritureFilter", "EcritureOut",
    "EcritureUpdate", "LigneIn", "LigneOut",
    # mobile money
    "MmRapprochementIn", "MmTransactionOut", "MtnMomoWebhookPayload",
    "OrangeMoneyWebhookPayload", "WaveWebhookPayload",
    # freeze
    "FreezeCascadeRuleOut", "FreezeEventOut", "FreezeRequest", "FreezeResultOut",
    "FreezeTargetOut", "TenantFreezeStateOut", "UnfreezeRequest",
]
