"""DTO Notifications & Communications."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

CanalT = Literal["email", "sms", "whatsapp", "push", "in_app"]
CriticiteT = Literal["info", "normale", "haute", "critique"]
StatutNotifT = Literal["queued", "sending", "sent", "delivered", "read", "clicked", "failed", "bounced", "suppressed", "retrying"]
StatutCampT = Literal["brouillon", "planifiee", "en_cours", "pause", "terminee", "annulee"]
TypeTemplateT = Literal["transactionnel", "marketing", "systeme", "securite"]
StatutTemplateT = Literal["brouillon", "en_revision", "publie", "deprecie", "archive"]


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATES
# ─────────────────────────────────────────────────────────────────────────────
class TemplateCreate(BaseModel):
    code: str = Field(min_length=2, max_length=60, pattern=r"^[A-Z0-9_]+$")
    libelle: str = Field(min_length=2, max_length=200)
    description: str | None = None
    canal: CanalT
    type_template: TypeTemplateT = "transactionnel"
    type_notification: str | None = None
    sujet: str | None = None
    contenu_html: str | None = None
    contenu_texte: str | None = None
    contenu_markdown: str | None = None
    variables_attendues: list[str] = Field(default_factory=list)
    whatsapp_template_name: str | None = None
    whatsapp_template_lang: str = "fr"

    @model_validator(mode="after")
    def coherent(self):
        if self.canal == "email" and not self.sujet:
            raise ValueError("sujet requis pour un template email")
        if self.canal in ("email", "in_app") and not (self.contenu_html or self.contenu_markdown):
            raise ValueError("contenu_html ou contenu_markdown requis")
        if self.canal in ("sms", "whatsapp") and not (self.contenu_texte or self.contenu_html):
            raise ValueError("contenu requis pour SMS/WhatsApp")
        return self


class TemplateUpdate(BaseModel):
    libelle: str | None = None
    description: str | None = None
    sujet: str | None = None
    contenu_html: str | None = None
    contenu_texte: str | None = None
    contenu_markdown: str | None = None
    variables_attendues: list[str] | None = None
    statut: StatutTemplateT | None = None


class TemplateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID | None
    code: str
    libelle: str
    description: str | None
    canal: str
    type_template: str
    type_notification: str | None
    sujet: str | None
    variables_attendues: list[str]
    version: int
    statut: str
    created_at: datetime
    updated_at: datetime


class TemplateDetailOut(TemplateOut):
    contenu_html: str | None
    contenu_texte: str | None
    contenu_markdown: str | None
    whatsapp_template_name: str | None


class TemplatePreviewIn(BaseModel):
    variables: dict[str, Any] = Field(default_factory=dict)


class TemplatePreviewOut(BaseModel):
    sujet: str | None
    contenu_html: str | None
    contenu_texte: str | None
    variables_manquantes: list[str]


# ─────────────────────────────────────────────────────────────────────────────
# PRÉFÉRENCES
# ─────────────────────────────────────────────────────────────────────────────
class PreferenceUpsert(BaseModel):
    type_notification: str = Field(min_length=1, max_length=50)
    canaux_actives: list[CanalT] = Field(default_factory=list)
    canal_prefere: CanalT | None = None
    quiet_hours_debut: int | None = Field(None, ge=0, le=23)
    quiet_hours_fin: int | None = Field(None, ge=0, le=23)
    max_par_jour: int | None = Field(None, ge=0, le=100)
    langue: str = Field("fr", min_length=2, max_length=5)


class PreferenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    type_notification: str
    canaux_actives: list[str]
    canal_prefere: str | None
    quiet_hours_debut: int | None
    quiet_hours_fin: int | None
    max_par_jour: int | None
    langue: str


# ─────────────────────────────────────────────────────────────────────────────
# ENVOI
# ─────────────────────────────────────────────────────────────────────────────
class SendNotificationIn(BaseModel):
    """Envoi d'une notification ad-hoc."""
    user_id: UUID | None = None
    portal_user_id: UUID | None = None
    destinataire_email: EmailStr | None = None
    destinataire_telephone: str | None = None
    destinataire_nom: str | None = None

    canal: CanalT
    type_notification: str = Field(min_length=2, max_length=50)
    criticite: CriticiteT = "normale"

    template_code: str | None = None
    sujet: str | None = None
    contenu_html: str | None = None
    contenu_texte: str | None = None
    contenu_markdown: str | None = None

    contexte: dict[str, Any] = Field(default_factory=dict)

    cible_type: str | None = None
    cible_id: UUID | None = None
    action_url: str | None = None
    action_label: str | None = None

    @model_validator(mode="after")
    def coherent(self):
        # Soit template_code, soit contenu inline
        if not self.template_code and not (self.contenu_html or self.contenu_texte or self.contenu_markdown):
            raise ValueError("template_code OU contenu inline requis")
        # Destinataire obligatoire
        if not any([self.user_id, self.portal_user_id, self.destinataire_email, self.destinataire_telephone]):
            raise ValueError("Au moins un destinataire requis")
        if self.canal == "email" and not (self.destinataire_email or self.user_id or self.portal_user_id):
            raise ValueError("Email destinataire requis pour le canal email")
        if self.canal == "sms" and not (self.destinataire_telephone or self.user_id or self.portal_user_id):
            raise ValueError("Téléphone requis pour le canal SMS")
        return self


class NotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID | None
    user_id: UUID | None
    portal_user_id: UUID | None
    destinataire_email: str | None
    destinataire_telephone: str | None
    canal: str
    type_notification: str
    criticite: str
    sujet: str | None
    statut: str
    provider: str | None
    provider_message_id: str | None
    nb_tentatives: int
    derniere_erreur: str | None
    queued_at: datetime
    sent_at: datetime | None
    delivered_at: datetime | None
    read_at: datetime | None
    clicked_at: datetime | None
    failed_at: datetime | None
    cout_xof: int
    created_at: datetime


class NotificationDetailOut(NotificationOut):
    contenu_html: str | None
    contenu_texte: str | None
    contexte: dict[str, Any]
    action_url: str | None
    action_label: str | None
    tracking_id: str | None


class BulkSendIn(BaseModel):
    """Envoi groupé (campagne ad-hoc)."""
    destinataires: list[dict[str, Any]] = Field(min_length=1, max_length=10_000)
    # Chaque dict : {"user_id": "...", "contexte": {...}}
    template_code: str
    canal: CanalT
    type_notification: str
    criticite: CriticiteT = "normale"
    planifiee_at: datetime | None = None


class BulkSendResult(BaseModel):
    nb_queued: int
    nb_suppressed: int
    nb_erreurs: int
    batch_id: str


# ─────────────────────────────────────────────────────────────────────────────
# CAMPAGNES
# ─────────────────────────────────────────────────────────────────────────────
class CampaignCreate(BaseModel):
    code: str = Field(min_length=2, max_length=30, pattern=r"^[A-Z0-9_-]+$")
    nom: str = Field(min_length=2, max_length=200)
    description: str | None = None
    template_id: UUID
    canal: CanalT
    segments: dict[str, Any] = Field(default_factory=dict)
    planifiee_at: datetime | None = None


class CampaignUpdate(BaseModel):
    nom: str | None = None
    description: str | None = None
    segments: dict[str, Any] | None = None
    planifiee_at: datetime | None = None
    statut: StatutCampT | None = None


class CampaignOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    nom: str
    description: str | None
    template_id: UUID
    canal: str
    segments: dict[str, Any]
    statut: str
    planifiee_at: datetime | None
    demarree_at: datetime | None
    terminee_at: datetime | None
    nb_cibles: int
    nb_envoyes: int
    nb_livres: int
    nb_ouverts: int
    nb_clics: int
    nb_desabonnements: int
    nb_erreurs: int
    cout_total_xof: int
    created_at: datetime


class CampaignStatsOut(BaseModel):
    campaign_id: UUID
    nb_cibles: int
    nb_envoyes: int
    nb_livres: int
    nb_ouverts: int
    nb_clics: int
    nb_erreurs: int
    taux_delivrabilite_pct: float
    taux_ouverture_pct: float
    taux_clic_pct: float
    taux_erreur_pct: float
    cout_total_xof: int
    cout_par_envoi_xof: float


# ─────────────────────────────────────────────────────────────────────────────
# SUPPRESSION
# ─────────────────────────────────────────────────────────────────────────────
class SuppressionCreate(BaseModel):
    email: EmailStr | None = None
    telephone: str | None = None
    motif: Literal["unsubscribe", "bounce", "complaint", "spam", "admin_block"]
    type_notification: str | None = None

    @model_validator(mode="after")
    def coherent(self):
        if not self.email and not self.telephone:
            raise ValueError("email ou telephone requis")
        return self


class SuppressionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID | None
    email: str | None
    telephone: str | None
    motif: str
    type_notification: str | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# PUSH DEVICES
# ─────────────────────────────────────────────────────────────────────────────
class PushDeviceRegisterIn(BaseModel):
    device_token: str = Field(min_length=20)
    platform: Literal["ios", "android", "web"]
    provider: Literal["fcm", "apns", "web_push"] = "fcm"
    device_model: str | None = None
    os_version: str | None = None
    app_version: str | None = None


class PushDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    platform: str
    provider: str
    device_model: str | None
    os_version: str | None
    app_version: str | None
    actif: bool
    derniere_utilisation_at: datetime | None


# ─────────────────────────────────────────────────────────────────────────────
# IN-APP
# ─────────────────────────────────────────────────────────────────────────────
class InAppNotificationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    type_notification: str
    sujet: str | None
    contenu_texte: str | None
    action_url: str | None
    action_label: str | None
    read_at: datetime | None
    created_at: datetime


class MarkReadIn(BaseModel):
    notification_ids: list[UUID] = Field(min_length=1)


# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────
class NotificationAnalyticsOut(BaseModel):
    tenant_id: UUID
    periode_debut: datetime
    periode_fin: datetime
    nb_envoyes: int
    nb_livres: int
    nb_ouverts: int
    nb_clics: int
    nb_erreurs: int
    taux_delivrabilite_pct: float
    taux_ouverture_pct: float
    taux_clic_pct: float
    cout_total_xof: int
    repartition_par_canal: dict[str, int]
    repartition_par_type: dict[str, int]
    top_5_types: list[dict[str, Any]]
