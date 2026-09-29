"""Modèles Notifications & Communications."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index,
    Integer, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# ─────────────────────────────────────────────────────────────────────────────
# TEMPLATE
# ─────────────────────────────────────────────────────────────────────────────
class NotificationTemplate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Template de notification (email, SMS, WhatsApp, push, in-app).
    Versionné : chaque modification incrémente la version.
    """
    __tablename__ = "notification_templates"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,   # NULL = template global système
        index=True,
    )

    code: Mapped[str] = mapped_column(String(60), nullable=False)
    libelle: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    canal: Mapped[str] = mapped_column(String(20), nullable=False)
    type_template: Mapped[str] = mapped_column(String(30), nullable=False)
    type_notification: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    # Contenu
    sujet: Mapped[str | None] = mapped_column(Text, nullable=True)   # Email uniquement
    contenu_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    contenu_texte: Mapped[str | None] = mapped_column(Text, nullable=True)
    contenu_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)   # In-app / push

    # Variables attendues (documentation + validation)
    variables_attendues: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # WhatsApp template (si canal=whatsapp)
    whatsapp_template_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    whatsapp_template_lang: Mapped[str] = mapped_column(
        String(5), nullable=False, default="fr", server_default="fr"
    )

    # Versioning
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )

    # Auteur
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", "canal", "version", name="uq_template_code_canal_version"),
        Index("idx_tpl_tenant_canal_statut", "tenant_id", "canal", "statut"),
        Index("idx_tpl_type_notif", "type_notification"),
    )

    def __repr__(self) -> str:
        return f"<NotificationTemplate {self.code} ({self.canal} v{self.version})>"


# ─────────────────────────────────────────────────────────────────────────────
# PRÉFÉRENCES UTILISATEUR
# ─────────────────────────────────────────────────────────────────────────────
class NotificationPreference(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Préférences de notification par utilisateur + type de notification.
    Permet à l'utilisateur de désactiver certains canaux ou types.
    """
    __tablename__ = "notification_preferences"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Le type de notification (ou "*" pour tout)
    type_notification: Mapped[str] = mapped_column(String(50), nullable=False)

    # Canaux activés (JSONB array)
    canaux_actives: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    canal_prefere: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Quiet hours (ne pas déranger entre X et Y)
    quiet_hours_debut: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 0-23
    quiet_hours_fin: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Fréquence max (par jour)
    max_par_jour: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Langue préférée
    langue: Mapped[str] = mapped_column(
        String(5), nullable=False, default="fr", server_default="fr"
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("user_id", "type_notification", name="uq_pref_user_type"),
    )

    def __repr__(self) -> str:
        return f"<NotificationPreference user={self.user_id} type={self.type_notification}>"


# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATION
# ─────────────────────────────────────────────────────────────────────────────
class Notification(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Une notification individuelle (envoyée ou en file d'attente).
    Contient le contenu final (après rendu template) pour audit.
    """
    __tablename__ = "notifications"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    template_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("notification_templates.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Destinataire
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    portal_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("portal_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Destinataire externe (email ou téléphone direct)
    destinataire_email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    destinataire_telephone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    destinataire_nom: Mapped[str | None] = mapped_column(String(120), nullable=True)

    # Classification
    canal: Mapped[str] = mapped_column(String(20), nullable=False)
    type_notification: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    criticite: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normale", server_default="normale"
    )

    # Contenu final (après rendu)
    sujet: Mapped[str | None] = mapped_column(Text, nullable=True)
    contenu_html: Mapped[str | None] = mapped_column(Text, nullable=True)
    contenu_texte: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Contexte (variables utilisées pour le rendu)
    contexte: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Cible (lien vers la ressource concernée)
    cible_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    cible_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    action_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    action_label: Mapped[str | None] = mapped_column(String(80), nullable=True)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", server_default="queued", index=True
    )

    # Provider utilisé
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)

    # Erreurs & retry
    nb_tentatives: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    derniere_erreur: Mapped[str | None] = mapped_column(Text, nullable=True)
    prochaine_tentative_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Timestamps
    queued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    clicked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Coût
    cout_xof: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Priorité
    priorite: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")

    # Campagne (si applicable)
    campaign_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("notification_campaigns.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    # Tracking
    tracking_id: Mapped[str | None] = mapped_column(String(64), nullable=True, unique=True)
    utm_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    utm_medium: Mapped[str | None] = mapped_column(String(30), nullable=True)
    utm_campaign: Mapped[str | None] = mapped_column(String(50), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_notif_tenant_statut", "tenant_id", "statut"),
        Index("idx_notif_user_date", "user_id", "created_at"),
        Index("idx_notif_type_date", "type_notification", "created_at"),
        Index("idx_notif_provider_msg", "provider_message_id"),
        Index("idx_notif_campagne", "campaign_id"),
    )

    def __repr__(self) -> str:
        return f"<Notification {self.type_notification} ({self.canal} → {self.statut})>"


# ─────────────────────────────────────────────────────────────────────────────
# CAMPAGNE
# ─────────────────────────────────────────────────────────────────────────────
class NotificationCampaign(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Campagne d'envoi groupé (newsletter, promo, annonce).
    """
    __tablename__ = "notification_campaigns"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(30), nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Contenu (référence à un template)
    template_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("notification_templates.id"),
        nullable=False,
    )
    canal: Mapped[str] = mapped_column(String(20), nullable=False)

    # Ciblage (JSONB : filtres users)
    segments: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # Ex : {"roles": ["ADMIN_TENANT"], "statut": "actif", "derniere_connexion_apres": "..."}

    # Planification
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )
    planifiee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    demarree_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    terminee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Statistiques (dénormalisées)
    nb_cibles: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_envoyes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_livres: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_ouverts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_clics: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_desabonnements: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_erreurs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    cout_total_xof: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Auteur
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_campaign_code"),
        Index("idx_camp_tenant_statut", "tenant_id", "statut"),
        Index("idx_camp_planifiee", "planifiee_at"),
    )

    def __repr__(self) -> str:
        return f"<NotificationCampaign {self.code} ({self.statut})>"


# ─────────────────────────────────────────────────────────────────────────────
# LOG D'ÉVÉNEMENT (tracking)
# ─────────────────────────────────────────────────────────────────────────────
class NotificationEvent(UUIDPrimaryKeyMixin, Base):
    """
    Événement lié à une notification (delivered, opened, clicked, bounced).
    Table immuable pour l'audit et l'analytics.
    """
    __tablename__ = "notification_events"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    notification_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Contexte technique
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_notif_evt_notif", "notification_id", "created_at"),
        Index("idx_notif_evt_tenant_type", "tenant_id", "event_type", "created_at"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# LISTE DE SUPPRESSION (opt-out)
# ─────────────────────────────────────────────────────────────────────────────
class NotificationSuppression(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Liste de suppression : emails/téléphones qui ne doivent PLUS recevoir de
    notifications marketing (RGPD-like).
    """
    __tablename__ = "notification_suppressions"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )

    email: Mapped[str | None] = mapped_column(String(150), nullable=True, index=True)
    telephone: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)

    motif: Mapped[str] = mapped_column(String(50), nullable=False)
    # unsubscribe | bounce | complaint | spam | admin_block

    type_notification: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # NULL = toute communication marketing

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "email", "type_notification", name="uq_suppression_email"),
        Index("idx_supp_email", "email"),
        Index("idx_supp_tel", "telephone"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# DEVICE PUSH (tokens FCM/APNS)
# ─────────────────────────────────────────────────────────────────────────────
class PushDevice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Appareil d'un utilisateur pour les notifications push."""
    __tablename__ = "push_devices"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    device_token: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False)   # ios | android | web
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="fcm", server_default="fcm")

    device_model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    os_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    app_version: Mapped[str | None] = mapped_column(String(30), nullable=True)

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    derniere_utilisation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_push_user_actif", "user_id", "actif"),
    )
