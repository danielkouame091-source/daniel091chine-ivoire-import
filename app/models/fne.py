"""Modèles FNE — Facturation Normalisée Électronique DGI CI."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger, Boolean, CheckConstraint, Date, DateTime, ForeignKey, Index,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION FNE PAR TENANT
# ─────────────────────────────────────────────────────────────────────────────
class FneConfiguration(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Configuration d'un tenant pour l'interfaçage FNE.
    Une seule config active par tenant à la fois.
    """
    __tablename__ = "fne_configurations"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identifiants DGI
    ncc: Mapped[str] = mapped_column(String(20), nullable=False)          # Numéro Compte Contribuable
    centre_rattachement: Mapped[str | None] = mapped_column(String(30), nullable=True)
    regime_imposition: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Environnement
    environnement: Mapped[str] = mapped_column(
        String(20), nullable=False, default="sandbox", server_default="sandbox"
    )   # sandbox | production
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)            # chiffré en DB
    api_key_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Identifiant unique entreprise
    entity_id: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Token OAuth (si utilisé)
    oauth_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    oauth_token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # État
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    certification_validee: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    date_validation_dgi: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Configuration par défaut
    template_defaut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="B2F", server_default="B2F"
    )   # B2B | B2C | B2F
    prefixe_reference: Mapped[str | None] = mapped_column(String(10), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_fne_conf_tenant_active", "tenant_id", "active"),
        CheckConstraint(
            "environnement IN ('sandbox','production')",
            name="fne_conf_env_valide",
        ),
    )

    def __repr__(self) -> str:
        return f"<FneConfiguration tenant={self.tenant_id} env={self.environnement} ncc={self.ncc}>"


# ─────────────────────────────────────────────────────────────────────────────
# FACTURE CERTIFIÉE FNE
# ─────────────────────────────────────────────────────────────────────────────
class FneInvoice(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Facture certifiée FNE.
    Lien vers la facture interne (customer_invoices) + données de certification DGI.
    """
    __tablename__ = "fne_invoices"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    customer_invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("customer_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    configuration_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("fne_configurations.id"),
        nullable=False,
    )

    # Identifiants DGI (après certification)
    fne_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    fne_reference: Mapped[str | None] = mapped_column(String(30), nullable=True, unique=True)
    fne_token: Mapped[str | None] = mapped_column(Text, nullable=True)         # code QR
    qr_code_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    fiscal_stamp: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Type de document
    document_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="invoice", server_default="invoice"
    )
    template: Mapped[str] = mapped_column(
        String(20), nullable=False, default="B2F", server_default="B2F"
    )

    # Numéro normalisé
    numero_normalise: Mapped[str | None] = mapped_column(String(30), nullable=True)
    annee_edition: Mapped[int] = mapped_column(Integer, nullable=False)
    sequence_annuelle: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="brouillon", server_default="brouillon"
    )
    date_soumission: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_certification: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    date_annulation: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Payload DGI
    payload_envoye: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    reponse_dgi: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Sticker
    sticker_consomme: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    balance_sticker_apres: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Retry
    nb_tentatives: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    derniere_erreur: Mapped[str | None] = mapped_column(Text, nullable=True)
    prochaine_tentative_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "customer_invoice_id", name="uq_fne_ci"),
        Index("idx_fne_tenant_statut", "tenant_id", "statut"),
        Index("idx_fne_tenant_reference", "tenant_id", "fne_reference"),
        Index("idx_fne_tenant_date", "tenant_id", "date_certification"),
        CheckConstraint(
            "statut IN ('brouillon','en_attente','certifiee','rejetee','annulee','expiree','error')",
            name="fne_inv_statut_valide",
        ),
    )

    def __repr__(self) -> str:
        return f"<FneInvoice {self.fne_reference or self.id} statut={self.statut}>"


# ─────────────────────────────────────────────────────────────────────────────
# LOG DES APPELS API FNE
# ─────────────────────────────────────────────────────────────────────────────
class FneApiLog(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Journal détaillé de chaque appel API FNE.
    Indispensable pour le support et l'audit.
    """
    __tablename__ = "fne_api_logs"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fne_invoice_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("fne_invoices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Requête
    methode: Mapped[str] = mapped_column(String(10), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    headers_envoyes: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    payload_envoye: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # Réponse
    statut_http: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reponse_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Performance
    latence_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tentatives: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    # Traçabilité
    correlation_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    created_by: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_fne_log_tenant_date", "tenant_id", "created_at"),
        Index("idx_fne_log_statut", "tenant_id", "statut_http"),
    )

    def __repr__(self) -> str:
        return f"<FneApiLog {self.methode} {self.url} → {self.statut_http}>"


# ─────────────────────────────────────────────────────────────────────────────
# STICKERS FNE
# ─────────────────────────────────────────────────────────────────────────────
class FneStickerBalance(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Suivi du solde de stickers FNE par tenant.
    Mis à jour à chaque certification et via l'endpoint balance-stickers.
    """
    __tablename__ = "fne_sticker_balances"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        unique=True,
    )

    balance_fne: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    balance_rne: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    balance_total: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )

    seuil_alerte: Mapped[int] = mapped_column(
        Integer, nullable=False, default=50, server_default="50"
    )
    derniere_sync_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    derniere_consommation_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_fne_sticker_tenant", "tenant_id"),
    )

    def __repr__(self) -> str:
        return f"<FneStickerBalance tenant={self.tenant_id} total={self.balance_total}>"


# ─────────────────────────────────────────────────────────────────────────────
# ÉVÉNEMENTS FNE (webhooks ou polling)
# ─────────────────────────────────────────────────────────────────────────────
class FneEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Événement FNE reçu (webhook DGI ou détecté par polling).
    Permet de tracer l'historique complet d'une facture certifiée.
    """
    __tablename__ = "fne_events"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    fne_invoice_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("fne_invoices.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    event_type: Mapped[str] = mapped_column(String(30), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    traite: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    traite_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    erreur_traitement: Mapped[str | None] = mapped_column(Text, nullable=True)

    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="webhook", server_default="webhook"
    )   # webhook | polling | manuel

    __table_args__ = (
        Index("idx_fne_event_tenant_date", "tenant_id", "created_at"),
        Index("idx_fne_event_type", "tenant_id", "event_type"),
    )

    def __repr__(self) -> str:
        return f"<FneEvent {self.event_type} invoice={self.fne_invoice_id}>"
