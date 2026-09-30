"""DTO Analytics temps réel."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

TypeAlerteT = Literal["seuil_montant", "seuil_volume", "seuil_vitesse", "variation_pct", "anomalie_statistique", "declenchement_manuel"]
SeveriteT = Literal["info", "warning", "critical", "emergency"]
StatutAlerteT = Literal["active", "acquittee", "resolue", "silencieuse", "escaladee"]
FenetreT = Literal["tumbling", "sliding", "session"]
GranulariteT = Literal["second", "minute", "hour", "day", "week", "month", "year"]


# ─────────────────────────────────────────────────────────────────────────────
# EVENT PUBLISH
# ─────────────────────────────────────────────────────────────────────────────
class EventPublishIn(BaseModel):
    topic: str = Field(min_length=3, max_length=100)
    event_type: str = Field(min_length=3, max_length=60)
    partition_key: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any]


class EventPublishedOut(BaseModel):
    event_id: UUID
    topic: str
    partition: int | None
    offset: int | None
    published: bool


# ─────────────────────────────────────────────────────────────────────────────
# ALERT RULES
# ─────────────────────────────────────────────────────────────────────────────
class AlertRuleCreateIn(BaseModel):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[A-Z0-9_-]+$")
    nom: str = Field(min_length=2, max_length=200)
    description: str | None = None

    type_alerte: TypeAlerteT
    severite: SeveriteT

    topic: str = Field(min_length=3, max_length=100)
    event_type: str | None = None
    filtre: dict[str, Any] = Field(default_factory=dict)

    condition: dict[str, Any]

    fenetre_type: FenetreT = "tumbling"
    fenetre_duree_s: int = Field(300, ge=10, le=86400)
    fenetre_slide_s: int | None = Field(None, ge=10, le=86400)

    cooldown_s: int = Field(300, ge=0, le=86400)

    actions: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="after")
    def coherent(self):
        if self.fenetre_type == "sliding" and not self.fenetre_slide_s:
            raise ValueError("fenetre_slide_s requis pour fenêtre glissante")
        if self.fenetre_slide_s and self.fenetre_slide_s >= self.fenetre_duree_s:
            raise ValueError("fenetre_slide_s doit être < fenetre_duree_s")
        return self


class AlertRuleUpdateIn(BaseModel):
    nom: str | None = None
    description: str | None = None
    severite: SeveriteT | None = None
    filtre: dict[str, Any] | None = None
    condition: dict[str, Any] | None = None
    fenetre_duree_s: int | None = Field(None, ge=10, le=86400)
    cooldown_s: int | None = Field(None, ge=0, le=86400)
    actions: list[dict[str, Any]] | None = None
    active: bool | None = None


class AlertRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    code: str
    nom: str
    description: str | None
    type_alerte: str
    severite: str
    topic: str
    event_type: str | None
    filtre: dict[str, Any]
    condition: dict[str, Any]
    fenetre_type: str
    fenetre_duree_s: int
    fenetre_slide_s: int | None
    cooldown_s: int
    actions: list[dict[str, Any]]
    active: bool
    dernier_declenchement_at: datetime | None
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# ALERTS
# ─────────────────────────────────────────────────────────────────────────────
class AlertAcquitIn(BaseModel):
    commentaire: str = Field(min_length=5, max_length=2000)


class AlertResolveIn(BaseModel):
    resolution: str = Field(min_length=5, max_length=2000)


class AlertEscalateIn(BaseModel):
    escaladee_a_user_id: UUID
    motif: str = Field(min_length=5, max_length=1000)


class RealtimeAlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID
    rule_id: UUID
    reference: str
    severite: str
    titre: str
    description: str
    event_declencheur: dict[str, Any]
    metriques: dict[str, Any]
    source_type: str | None
    source_id: UUID | None
    statut: str
    acquittee_par_user_id: UUID | None
    acquittee_at: datetime | None
    commentaire_acquittement: str | None
    resolue_at: datetime | None
    resolution: str | None
    escaladee: bool
    escalade_at: datetime | None
    actions_executees: list[dict[str, Any]]
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD TEMPS RÉEL
# ─────────────────────────────────────────────────────────────────────────────
class RealtimeQueryIn(BaseModel):
    metric: str = Field(min_length=2, max_length=100)
    granularite: GranulariteT = "minute"
    depuis_s: int = Field(3600, ge=60, le=2592000)   # max 30 jours
    filtres: dict[str, Any] = Field(default_factory=dict)


class RealtimeMetricPoint(BaseModel):
    timestamp: datetime
    value: float
    labels: dict[str, str] = Field(default_factory=dict)


class RealtimeQueryOut(BaseModel):
    metric: str
    granularite: str
    depuis_s: int
    points: list[RealtimeMetricPoint]
    total: float
    minimum: float
    maximum: float
    moyenne: float
    duree_requete_ms: int


class RealtimeDashboardOut(BaseModel):
    code: str
    nom: str
    description: str
    widgets: list[dict[str, Any]]
    data: dict[str, Any]
    refresh_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# MATERIALIZED VIEW
# ─────────────────────────────────────────────────────────────────────────────
class MaterializedViewCreateIn(BaseModel):
    nom: str = Field(min_length=3, max_length=100, pattern=r"^[a-z][a-z0-9_]*$")
    description: str | None = None
    source_table: str = Field(min_length=3, max_length=100)
    ch_sql: str = Field(min_length=20)
    granularite: GranulariteT
    refresh_mode: Literal["incremental", "full", "on_demand"] = "incremental"
    refresh_interval_s: int = Field(60, ge=10, le=3600)


class MaterializedViewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    tenant_id: UUID | None
    nom: str
    description: str | None
    source_table: str
    granularite: str
    refresh_mode: str
    refresh_interval_s: int
    derniere_refresh_at: datetime | None
    derniere_refresh_duree_ms: int | None
    nb_lignes: int
    taille_mb: float
    active: bool
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# WEBSOCKET
# ─────────────────────────────────────────────────────────────────────────────
class WebSocketSubscribeIn(BaseModel):
    topics: list[str] = Field(min_length=1, max_length=20)


class WebSocketSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    session_id: str
    user_id: UUID | None
    topics_abonnes: list[str]
    connecte_at: datetime
    derniere_activite_at: datetime
    nb_messages_envoyes: int


class WebSocketMessageOut(BaseModel):
    type: Literal["event", "alert", "metric", "ping", "subscribed", "error"]
    topic: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime


# ─────────────────────────────────────────────────────────────────────────────
# PIPELINE
# ─────────────────────────────────────────────────────────────────────────────
class PipelineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    code: str
    nom: str
    description: str | None
    topic: str
    consumer_group: str
    transformation_type: str
    table_cible: str
    active: bool
    nb_events_traites: int
    nb_erreurs: int
    lag_seconds: float
    dernier_event_at: datetime | None
    created_at: datetime


class ConsumerLagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    consumer_group: str
    topic: str
    partition: int
    lag: int
    offset_consumer: int
    offset_latest: int
    created_at: datetime


# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS DASHBOARD (fondateur)
# ─────────────────────────────────────────────────────────────────────────────
class RealtimeAnalyticsOut(BaseModel):
    date_arret: datetime
    # Volumétrie
    nb_events_24h: int
    nb_events_1h: int
    events_par_seconde: float
    # Santé Kafka
    kafka_lag_total: int
    kafka_topics_actifs: int
    # Alertes
    nb_alertes_actives: int
    nb_alertes_critiques: int
    nb_alertes_24h: int
    # Performance
    latence_p50_ms: float
    latence_p95_ms: float
    latence_p99_ms: float
    # WebSocket
    nb_connexions_actives: int
    nb_messages_envoyes_24h: int
    # Top topics
    top_topics: list[dict[str, Any]]
    top_tenants: list[dict[str, Any]]
