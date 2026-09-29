"""Modèles API publique — Clients, Clés, Webhooks, Livraisons, Logs d'usage."""
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
# CLIENT API
# ─────────────────────────────────────────────────────────────────────────────
class ApiClient(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Client API (partenaire, expert-comptable, développeur).
    Un client peut avoir plusieurs clés API (rotation).
    """
    __tablename__ = "api_clients"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    code: Mapped[str] = mapped_column(String(30), nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    type_client: Mapped[str] = mapped_column(String(30), nullable=False)

    # Contact
    contact_nom: Mapped[str | None] = mapped_column(String(120), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(150), nullable=True)
    contact_telephone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    organisation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Environnement
    environnement: Mapped[str] = mapped_column(
        String(20), nullable=False, default="production", server_default="production"
    )

    # Configuration
    webhook_url_racine: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_whitelist: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    webhook_secret_enc: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Rate limit (override du défaut)
    rate_limit_per_minute: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quota_mensuel: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Statut
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_api_client_code"),
        Index("idx_api_client_tenant_actif", "tenant_id", "actif"),
        Index("idx_api_client_type", "tenant_id", "type_client"),
    )

    def __repr__(self) -> str:
        return f"<ApiClient {self.code} ({self.type_client})>"


# ─────────────────────────────────────────────────────────────────────────────
# CLÉ API
# ─────────────────────────────────────────────────────────────────────────────
class ApiKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Clé API. La clé en clair n'est affichée qu'à la création.
    Seul le hash est stocké en DB.
    """
    __tablename__ = "api_keys"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    api_client_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("api_clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identification
    prefix: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # Ex : "mtech_live_abc123" → préfixe affiché à l'utilisateur
    nom: Mapped[str] = mapped_column(Text, nullable=False)

    # Hash de la clé
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    # Scopes autorisés
    scopes: Mapped[list[str]] = mapped_column(JSONB, nullable=False)

    # Environnement
    environnement: Mapped[str] = mapped_column(String(20), nullable=False)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )

    # Expiration
    expire_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Rotation
    remplace_cle_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("api_keys.id"), nullable=True
    )
    remplacee_par_cle_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("api_keys.id"), nullable=True
    )

    # Usage
    derniere_utilisation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    derniere_utilisation_ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    nb_requetes_total: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )

    # Révocation
    revoquee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    motif_revocation: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index("idx_api_key_tenant_statut", "tenant_id", "statut"),
        Index("idx_api_key_prefix", "prefix"),
    )

    def __repr__(self) -> str:
        return f"<ApiKey {self.prefix}... ({self.statut})>"


# ─────────────────────────────────────────────────────────────────────────────
# WEBHOOK ENDPOINT
# ─────────────────────────────────────────────────────────────────────────────
class WebhookEndpoint(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Endpoint webhook sortant.
    Un client API peut avoir plusieurs endpoints (différents événements).
    """
    __tablename__ = "webhook_endpoints"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    api_client_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("api_clients.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identification
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # URL cible
    url: Mapped[str] = mapped_column(Text, nullable=False)

    # Secret HMAC (chiffré en DB)
    secret_enc: Mapped[str] = mapped_column(Text, nullable=False)

    # Événements souscrits
    events: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    # ["invoice.created", "payment.received"]

    # En-têtes custom (ex: auth partenaire)
    headers_custom: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    # Statut
    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    # Statistiques (dénormalisées)
    nb_deliveries_total: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    nb_succes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    nb_echecs: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    # Dernière livraison
    derniere_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    derniere_delivery_statut: Mapped[str | None] = mapped_column(String(20), nullable=True)
    dernier_code_http: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Circuit breaker (si trop d'échecs → désactivation auto)
    echecs_consecutifs: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    desactive_auto_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("api_client_id", "url", name="uq_webhook_endpoint_url"),
        Index("idx_webhook_endpoint_tenant_actif", "tenant_id", "actif"),
    )

    def __repr__(self) -> str:
        return f"<WebhookEndpoint {self.nom} → {self.url}>"


# ─────────────────────────────────────────────────────────────────────────────
# LIVRAISON WEBHOOK
# ─────────────────────────────────────────────────────────────────────────────
class WebhookDelivery(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Une livraison webhook (tentative d'envoi).
    """
    __tablename__ = "webhook_deliveries"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    endpoint_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("webhook_endpoints.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Identification
    delivery_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)

    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)

    # Payload
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_size_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # En-têtes signés
    signature: Mapped[str] = mapped_column(String(128), nullable=False)
    timestamp: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending"
    )

    # Tentatives
    nb_tentatives: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    max_tentatives: Mapped[int] = mapped_column(Integer, nullable=False, default=7, server_default="7")
    prochaine_tentative_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Réponse
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_headers: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    latence_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    erreur: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Timestamps
    premiere_tentative_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    derniere_tentative_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reussie_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Source métier (traçabilité)
    source_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_webhook_del_tenant_statut", "tenant_id", "statut"),
        Index("idx_webhook_del_endpoint_date", "endpoint_id", "created_at"),
        Index("idx_webhook_del_prochaine", "prochaine_tentative_at"),
        Index("idx_webhook_del_event", "tenant_id", "event_type"),
    )

    def __repr__(self) -> str:
        return f"<WebhookDelivery {self.delivery_id} ({self.event_type}) statut={self.statut}>"


# ─────────────────────────────────────────────────────────────────────────────
# LOG D'USAGE API
# ─────────────────────────────────────────────────────────────────────────────
class ApiUsageLog(UUIDPrimaryKeyMixin, Base):
    """
    Log de chaque requête API publique.
    Table immuable pour audit + facturation.
    """
    __tablename__ = "api_usage_logs"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    api_client_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("api_clients.id", ondelete="SET NULL"),
        nullable=True,
    )
    api_key_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("api_keys.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Requête
    methode: Mapped[str] = mapped_column(String(10), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)
    query_params: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    scopes_requis: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    # Client
    ip: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    # Réponse
    statut_http: Mapped[int] = mapped_column(Integer, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latence_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Idempotence
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)

    # Facturation
    cout_unitaire_xof: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    facture: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_api_log_tenant_date", "tenant_id", "created_at"),
        Index("idx_api_log_client_date", "api_client_id", "created_at"),
        Index("idx_api_log_statut", "tenant_id", "statut_http"),
    )

    def __repr__(self) -> str:
        return f"<ApiUsageLog {self.methode} {self.endpoint} → {self.statut_http}>"


# ─────────────────────────────────────────────────────────────────────────────
# AGRÉGAT D'USAGE (cache)
# ─────────────────────────────────────────────────────────────────────────────
class ApiUsageAggregate(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Agrégat d'usage par client + granularité (minute, heure, jour, mois).
    Utilisé pour le rate limiting et la facturation.
    """
    __tablename__ = "api_usage_aggregates"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    api_client_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("api_clients.id", ondelete="CASCADE"),
        nullable=False,
    )

    granularite: Mapped[str] = mapped_column(String(20), nullable=False)
    periode: Mapped[str] = mapped_column(String(30), nullable=False)   # "2025-12-15T14:30"

    # Compteurs
    nb_requetes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_succes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_erreurs_4xx: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_erreurs_5xx: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    nb_rate_limited: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # Performance
    latence_moyenne_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latence_p95_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Coût
    cout_total_xof: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")

    __table_args__ = (
        UniqueConstraint(
            "api_client_id", "granularite", "periode",
            name="uq_api_usage_aggregate",
        ),
        Index("idx_api_agg_tenant_periode", "tenant_id", "granularite", "periode"),
    )

    def __repr__(self) -> str:
        return f"<ApiUsageAggregate {self.granularite}:{self.periode} n={self.nb_requetes}>"


# ─────────────────────────────────────────────────────────────────────────────
# IDEMPOTENCY KEY
# ─────────────────────────────────────────────────────────────────────────────
class IdempotencyKey(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Clés d'idempotence pour les POST (éviter les doublons sur retry client).
    """
    __tablename__ = "idempotency_keys"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    api_client_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("api_clients.id", ondelete="CASCADE"),
        nullable=False,
    )

    key: Mapped[str] = mapped_column(String(128), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(200), nullable=False)

    # Réponse mise en cache
    response_status: Mapped[int] = mapped_column(Integer, nullable=False)
    response_body: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    # Expiration (24h par défaut)
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("api_client_id", "key", name="uq_idempotency_client_key"),
        Index("idx_idempotency_expire", "expire_at"),
    )
