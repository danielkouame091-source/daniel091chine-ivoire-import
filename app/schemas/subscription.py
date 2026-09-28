"""DTO Abonnements SaaS — plans, souscriptions, paiements."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import MMProvider, SubPlan, SubStatut


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: SubPlan
    libelle: str
    prix_mensuel_xof: int
    prix_annuel_xof: int
    max_users: int
    max_ecritures_mois: int
    max_mm_transactions: int
    features: dict


class SubscriptionCreate(BaseModel):
    plan_code: SubPlan
    duree_mois: int = Field(1, ge=1, le=24)
    mode_paiement: str = Field(pattern=r"^(wave|orange_money|mtn_momo|moov_money|virement|espece|carte)$")
    reference_paiement: str | None = None
    auto_renouvellement: bool = False


class SubscriptionRenewIn(BaseModel):
    duree_mois: int = Field(ge=1, le=24)
    mode_paiement: str


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    tenant_id: UUID
    plan_id: UUID
    statut: SubStatut
    periode_debut: datetime
    periode_fin: datetime
    grace_jours: int
    montant_xof: int
    devise: str
    mode_paiement: str | None
    reference_paiement: str | None
    auto_renouvellement: bool
    created_at: datetime


class SubscriptionStatusOut(BaseModel):
    """État calculé, utilisé par le middleware read-only."""
    statut: SubStatut
    periode_fin: datetime
    jours_restants: int
    est_expiree: bool
    est_en_grace: bool
    force_read_only: bool
    plan_code: SubPlan | None = None


class SubscriptionPaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    subscription_id: UUID
    montant_xof: int
    mode_paiement: str
    reference_externe: str | None
    provider: MMProvider | None
    statut: str
    confirme_at: datetime | None
    created_at: datetime
