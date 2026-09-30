"""Modèles Analytics temps réel — Alertes, Dashboards, Pipelines, Buffer."""
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
# EVENT BUFFER (fiabilité : écriture en PG avant Kafka)
# ─────────────────────────────────────────────────────────────────────────────
class EventBuffer(UUIDPrimaryKeyMixin, Base):
    """
    Buffer d'events : écriture synchrone en PG (WAL) puis publication Kafka async.
    Garantit zéro perte même si Kafka est down.
    """
    __tablename__ = "realtime_event_buffer"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    topic: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    partition_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_size_kb: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Statut de publication
    published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    kafka_offset: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kafka_partition: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nb_tentatives: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    derniere_erreur: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_evt_buffer_tenant_date", "tenant_id", "created_at"),
        Index("idx_evt_buffer_published", "published", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<EventBuffer {self.topic}#{self.event_type}>"


# ─────────────────────────────────────────────────────────────────────────────
# SCHÉMA REGISTRY (contrat des topics)
# ─────────────────────────────────────────────────────────────────────────────
class TopicSchema(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Contrat JSON Schema d'un topic. Versionné pour éviter les breaking changes.
    """
    __tablename__ = "realtime_topic_schemas"

    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)

    json_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    champs_requis: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")

    # Compatibilité
    compat_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="backward", server_default="backward"
    )   # backward | forward | full | none

    actif: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    deprecie_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("topic", "version", name="uq_topic_schema_version"),
        Index("idx_topic_schema_actif", "topic", "actif"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# ALERT RULES (règles d'alerte)
# ─────────────────────────────────────────────────────────────────────────────
class AlertRule(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Règle d'alerte évaluée en streaming.
    """
    __tablename__ = "realtime_alert_rules"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Type et configuration
    type_alerte: Mapped[str] = mapped_column(String(30), nullable=False)
    severite: Mapped[str] = mapped_column(String(20), nullable=False)

    # Source
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    filtre: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

    # Condition
    condition: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    # Ex seuil_montant : {"field": "montant_xof", "operator": ">", "value": 1000000}
    # Ex seuil_volume : {"window_s": 300, "threshold": 50}
    # Ex variation_pct : {"field": "montant_xof", "period_s": 3600, "threshold_pct": 50}

    # Fenêtre temporelle
    fenetre_type: Mapped[str] = mapped_column(String(20), nullable=False, default="tumbling", server_default="tumbling")
    fenetre_duree_s: Mapped[int] = mapped_column(Integer, nullable=False, default=300, server_default="300")
    fenetre_slide_s: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Cooldown anti-spam
    cooldown_s: Mapped[int] = mapped_column(Integer, nullable=False, default=300, server_default="300")
    dernier_declenchement_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Actions
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list, server_default="[]")
    # Ex : [{"type": "notification", "canal": "whatsapp", "destinataires": ["..."]}]
    # Ex : [{"type": "webhook", "url": "https://..."}]
    # Ex : [{"type": "freeze_tenant"}]  → gel automatique

    # Statut
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_alert_rule_code"),
        Index("idx_alert_rule_tenant_active", "tenant_id", "active"),
        Index("idx_alert_rule_topic", "topic"),
    )

    def __repr__(self) -> str:
        return f"<AlertRule {self.code} ({self.severite})>"


# ─────────────────────────────────────────────────────────────────────────────
# ALERTS (alertes déclenchées)
# ─────────────────────────────────────────────────────────────────────────────
class RealtimeAlert(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Alerte déclenchée par une règle.
    """
    __tablename__ = "realtime_alerts"

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    rule_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("realtime_alert_rules.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    reference: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)

    severite: Mapped[str] = mapped_column(String(20), nullable=False)
    titre: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Données déclenchantes
    event_declencheur: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    metriques: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default="{}")

    # Source
    source_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    source_id: Mapped[UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    # Statut
    statut: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active", server_default="active"
    )

    # Accusé de réception
    acquittee_par_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    acquittee_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commentaire_acquittement: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Résolution
    resolue_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Escalade
    escaladee: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    escalade_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    escaladee_a_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    # Actions exécutées
    actions_executees: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_alert_tenant_statut", "tenant_id", "statut"),
        Index("idx_alert_tenant_severite", "tenant_id", "severite"),
        Index("idx_alert_tenant_date", "tenant_id", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<RealtimeAlert {self.reference} ({self.severite})>"


# ─────────────────────────────────────────────────────────────────────────────
# MATERIALIZED VIEW (dashboards temps réel côté ClickHouse)
# ─────────────────────────────────────────────────────────────────────────────
class MaterializedView(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Vue matérialisée ClickHouse : agrégation pré-calculée pour dashboards.
    """
    __tablename__ = "realtime_materialized_views"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True,   # NULL = globale (partagée entre tenants)
        index=True,
    )

    nom: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source
    source_table: Mapped[str] = mapped_column(String(100), nullable=False)
    ch_sql: Mapped[str] = mapped_column(Text, nullable=False)   # Requête ClickHouse

    # Résolution
    granularite: Mapped[str] = mapped_column(String(20), nullable=False)

    # Refresh
    refresh_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="incremental", server_default="incremental"
    )   # incremental | full | on_demand
    refresh_interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=60, server_default="60")
    derniere_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    derniere_refresh_duree_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Stats
    nb_lignes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    taille_mb: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False, default=0, server_default="0")

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        UniqueConstraint("tenant_id", "nom", name="uq_mv_tenant_nom"),
        Index("idx_mv_tenant_active", "tenant_id", "active"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE (ETL Kafka → ClickHouse)
# ─────────────────────────────────────────────────────────────────────────────
class DataPipeline(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Pipeline de transformation Kafka → ClickHouse.
    Définit : consumer group, transformations, table cible.
    """
    __tablename__ = "realtime_pipelines"

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    nom: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Source
    topic: Mapped[str] = mapped_column(String(100), nullable=False)
    consumer_group: Mapped[str] = mapped_column(String(100), nullable=False)

    # Transformation (Python code ou SQL)
    transformation_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="sql", server_default="sql"
    )   # sql | python | none
    transformation: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Cible
    table_cible: Mapped[str] = mapped_column(String(100), nullable=False)

    # Statut
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")

    # Statistiques
    nb_events_traites: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    nb_erreurs: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, server_default="0")
    lag_seconds: Mapped[float] = mapped_column(Numeric(10, 3), nullable=False, default=0, server_default="0")
    dernier_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_pipeline_active", "active"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# WEBSOCKET SESSIONS (tracking connexions temps réel)
# ─────────────────────────────────────────────────────────────────────────────
class WebSocketSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """
    Session WebSocket active (pour tracking + broadcast ciblé).
    """
    __tablename__ = "realtime_ws_sessions"

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=True, index=True,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )

    session_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    topics_abonnes: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    # Connexion
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Activité
    connecte_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    deconnecte_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    derniere_activite_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    nb_messages_envoyes: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    __table_args__ = (
        Index("idx_ws_tenant_active", "tenant_id", "deconnecte_at"),
    )


# ─────────────────────────────────────────────────────────────────────────────
# CONSUMER LAG (monitoring)
# ─────────────────────────────────────────────────────────────────────────────
class ConsumerLagSnapshot(UUIDPrimaryKeyMixin, Base):
    """
    Snapshot périodique du lag Kafka par consumer group.
    """
    __tablename__ = "realtime_consumer_lag"

    consumer_group: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    topic: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    partition: Mapped[int] = mapped_column(Integer, nullable=False)

    lag: Mapped[int] = mapped_column(BigInteger, nullable=False)
    offset_consumer: Mapped[int] = mapped_column(BigInteger, nullable=False)
    offset_latest: Mapped[int] = mapped_column(BigInteger, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("idx_lag_group_topic", "consumer_group", "topic", "created_at"),
    )
