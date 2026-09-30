"""
Référentiel Analytics Temps Réel.

Architecture :
- Kafka (Redpanda) : bus d'événements (ingestion, replay, partitionnement)
- ClickHouse : stockage OLAP columnar (agrégations < 100ms sur 100M+ lignes)
- WebSocket : diffusion temps réel aux clients connectés
- ARQ workers : consumers Kafka → ClickHouse + alerting

Topics Kafka (partition par tenant_id pour garantir l'ordre) :
- mtech.ecritures           : écritures comptables créées/validées
- mtech.factures.clients    : factures clients
- mtech.factures.fourniss.  : factures fournisseurs
- mtech.paiements           : encaissements + décaissements
- mtech.mm.transactions     : Mobile Money (Wave, OM, MTN, Moov)
- mtech.fne.certifications  : certifications FNE
- mtech.stock.mouvements    : entrées/sorties de stock
- mtech.rh.evenements       : congés, paie, embauches
- mtech.audit.events        : audit trail temps réel
- mtech.system.metrics      : métriques système
- mtech.alerts              : alertes générées
"""
from __future__ import annotations

from typing import NamedTuple


# ─────────────────────────────────────────────────────────────────────────────
# Topics Kafka (nom canonique)
# ─────────────────────────────────────────────────────────────────────────────
class KafkaTopic:
    ECRITURES = "mtech.ecritures"
    FACTURES_CLIENTS = "mtech.factures.clients"
    FACTURES_FOURNISSEURS = "mtech.factures.fournisseurs"
    PAIEMENTS = "mtech.paiements"
    MM_TRANSACTIONS = "mtech.mm.transactions"
    FNE_CERTIFICATIONS = "mtech.fne.certifications"
    STOCK_MOUVEMENTS = "mtech.stock.mouvements"
    RH_EVENEMENTS = "mtech.rh.evenements"
    AUDIT_EVENTS = "mtech.audit.events"
    SYSTEM_METRICS = "mtech.system.metrics"
    ALERTS = "mtech.alerts"


TOUS_TOPICS = {
    KafkaTopic.ECRITURES,
    KafkaTopic.FACTURES_CLIENTS,
    KafkaTopic.FACTURES_FOURNISSEURS,
    KafkaTopic.PAIEMENTS,
    KafkaTopic.MM_TRANSACTIONS,
    KafkaTopic.FNE_CERTIFICATIONS,
    KafkaTopic.STOCK_MOUVEMENTS,
    KafkaTopic.RH_EVENEMENTS,
    KafkaTopic.AUDIT_EVENTS,
    KafkaTopic.SYSTEM_METRICS,
    KafkaTopic.ALERTS,
}


# ─────────────────────────────────────────────────────────────────────────────
# Types d'événements métier
# ─────────────────────────────────────────────────────────────────────────────
class EventType:
    # Écritures
    ECRITURE_CREATED = "ecriture.created"
    ECRITURE_VALIDATED = "ecriture.validated"
    ECRITURE_LETTRAGE = "ecriture.lettrage"

    # Factures clients
    INVOICE_CREATED = "invoice.created"
    INVOICE_VALIDATED = "invoice.validated"
    INVOICE_PAID = "invoice.paid"
    INVOICE_OVERDUE = "invoice.overdue"

    # Factures fournisseurs
    SUPPLIER_INVOICE_CREATED = "supplier_invoice.created"
    SUPPLIER_INVOICE_VALIDATED = "supplier_invoice.validated"
    SUPPLIER_INVOICE_PAID = "supplier_invoice.paid"

    # Paiements
    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_SENT = "payment.sent"

    # Mobile Money
    MM_TX_RECEIVED = "mm.transaction.received"
    MM_TX_RECONCILED = "mm.transaction.reconciled"

    # FNE
    FNE_CERTIFIED = "fne.certified"
    FNE_REJECTED = "fne.rejected"

    # Stock
    STOCK_ENTRY = "stock.entry"
    STOCK_EXIT = "stock.exit"
    STOCK_LOW = "stock.low"

    # RH
    LEAVE_REQUESTED = "leave.requested"
    LEAVE_APPROVED = "leave.approved"
    PAYSLIP_GENERATED = "payslip.generated"

    # Audit
    AUDIT_FINDING_CRITICAL = "audit.finding.critical"
    AUDIT_FRAUD_DETECTED = "audit.fraud.detected"

    # Système
    SERVICE_HEALTH = "system.service_health"
    API_LATENCY = "system.api_latency"


# ─────────────────────────────────────────────────────────────────────────────
# Schémas d'événements (contrat strict)
# ─────────────────────────────────────────────────────────────────────────────
class EventoSchema(NamedTuple):
    topic: str
    event_type: str
    champs_requis: list[str]
    version: str


SCHEMAS_EVENEMENTS: list[EventoSchema] = [
    EventoSchema(
        topic=KafkaTopic.ECRITURES,
        event_type=EventType.ECRITURE_CREATED,
        champs_requis=["tenant_id", "ecriture_id", "numero_piece", "date_ecriture", "total_debit", "total_credit"],
        version="1.0",
    ),
    EventoSchema(
        topic=KafkaTopic.FACTURES_CLIENTS,
        event_type=EventType.INVOICE_PAID,
        champs_requis=["tenant_id", "invoice_id", "numero", "total_ttc", "date_paiement"],
        version="1.0",
    ),
    EventoSchema(
        topic=KafkaTopic.MM_TRANSACTIONS,
        event_type=EventType.MM_TX_RECEIVED,
        champs_requis=["tenant_id", "provider", "external_id", "montant_xof", "sens"],
        version="1.0",
    ),
    EventoSchema(
        topic=KafkaTopic.FNE_CERTIFICATIONS,
        event_type=EventType.FNE_CERTIFIED,
        champs_requis=["tenant_id", "invoice_id", "fne_reference", "numero_normalise"],
        version="1.0",
    ),
    # ... (à compléter pour chaque type)
]


# ─────────────────────────────────────────────────────────────────────────────
# Tables ClickHouse (catalogue)
# ─────────────────────────────────────────────────────────────────────────────
class ClickHouseTable:
    EVENTS = "mtech_events"                    # Table principale de tous les events
    ECRITURES = "mtech_ecritures"
    FACTURES_CLIENTS = "mtech_factures_clients"
    PAIEMENTS = "mtech_paiements"
    MM_TRANSACTIONS = "mtech_mm_transactions"
    FNE_CERTIFICATIONS = "mtech_fne_certifications"
    ALERTS = "mtech_alerts"
    METRICS_AGGR = "mtech_metrics_aggregated"


# ─────────────────────────────────────────────────────────────────────────────
# Résolutions temporelles supportées
# ─────────────────────────────────────────────────────────────────────────────
class Granularite:
    SECONDE = "second"
    MINUTE = "minute"
    HEURE = "hour"
    JOUR = "day"
    SEMAINE = "week"
    MOIS = "month"
    ANNEE = "year"


# ─────────────────────────────────────────────────────────────────────────────
# Types de fenêtres d'agrégation (stream processing)
# ─────────────────────────────────────────────────────────────────────────────
class FenetreType:
    TUMBLING = "tumbling"      # Fenêtres fixes non chevauchantes
    SLIDING = "sliding"        # Fenêtres glissantes
    SESSION = "session"        # Regroupement par activité


# ─────────────────────────────────────────────────────────────────────────────
# Types d'alertes (règles)
# ─────────────────────────────────────────────────────────────────────────────
class TypeAlerte:
    SEUIL_MONTANT = "seuil_montant"                # Montant > X
    SEUIL_VOLUME = "seuil_volume"                  # N events > X en T secondes
    SEUIL_VITESSE = "seuil_vitesse"                # Vitesse > X/sec
    VARIATION_PCT = "variation_pct"                # Variation > X% vs période précédente
    ANOMALIE_STATISTIQUE = "anomalie_statistique"  # Écart-type > 3σ
    DECLENCHEMENT_MANUEL = "declenchement_manuel"


# ─────────────────────────────────────────────────────────────────────────────
# Niveaux de sévérité d'alerte
# ─────────────────────────────────────────────────────────────────────────────
class SeveriteAlerte:
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"


SEVERITE_POIDS = {
    SeveriteAlerte.INFO: 1,
    SeveriteAlerte.WARNING: 2,
    SeveriteAlerte.CRITICAL: 3,
    SeveriteAlerte.EMERGENCY: 4,
}


# ─────────────────────────────────────────────────────────────────────────────
# Statuts d'alerte
# ─────────────────────────────────────────────────────────────────────────────
class StatutAlerte:
    ACTIVE = "active"
    ACQUITTEE = "acquittee"
    RESOLUE = "resolue"
    SILENCIEE = "silencieuse"
    ESCALADEE = "escaladee"


# ─────────────────────────────────────────────────────────────────────────────
# Configuration Kafka / Redpanda
# ─────────────────────────────────────────────────────────────────────────────
class KafkaConfig:
    BOOTSTRAP_SERVERS_ENV = "KAFKA_BOOTSTRAP_SERVERS"
    DEFAULT_BOOTSTRAP = "redpanda:9092"
    DEFAULT_PARTITIONS = 12           # 12 pour permettre 12 consumers en parallèle
    DEFAULT_REPLICATION = 3           # 3 réplicas en prod (1 en dev)
    COMPRESSION = "zstd"              # zstd : meilleur ratio
    MAX_MESSAGE_BYTES = 1_048_576     # 1 Mo
    RETENTION_HOURS = 168             # 7 jours de rétention
    ACKS = "all"                      # Durabilité maximale
    IDEMPOTENT_PRODUCER = True
    LINGER_MS = 5                     # Batching : 5ms max
    BATCH_SIZE = 16384                # 16 Ko par batch


# ─────────────────────────────────────────────────────────────────────────────
# Configuration ClickHouse
# ─────────────────────────────────────────────────────────────────────────────
class ClickHouseConfig:
    HOST_ENV = "CLICKHOUSE_HOST"
    PORT_ENV = "CLICKHOUSE_PORT"
    DEFAULT_PORT = 8123               # HTTP interface
    DEFAULT_DATABASE = "mtech_analytics"
    DEFAULT_USER = "default"
    MAX_CONNECTIONS = 20
    QUERY_TIMEOUT_S = 30
    MAX_RESULT_ROWS = 100_000
    # Buffer d'insertion
    INSERT_BATCH_SIZE = 1000
    INSERT_FLUSH_INTERVAL_MS = 500


# ─────────────────────────────────────────────────────────────────────────────
# Configuration WebSocket
# ─────────────────────────────────────────────────────────────────────────────
class WebSocketConfig:
    MAX_CONNECTIONS_PER_TENANT = 50
    HEARTBEAT_INTERVAL_S = 30
    MESSAGE_QUEUE_MAX = 1000          # Backpressure : drop si dépassé
    AUTH_TIMEOUT_S = 10               # Auth requise dans les 10s


# ─────────────────────────────────────────────────────────────────────────────
# Résolutions dashboard temps réel
# ─────────────────────────────────────────────────────────────────────────────
DASHBOARDS_TEMPS_REEL = [
    {
        "code": "flux_ventes",
        "nom": "Flux de ventes",
        "description": "Factures clients en temps réel (5 dernières minutes)",
        "widgets": [
            {"type": "counter", "kpi": "nb_factures_5min"},
            {"type": "line_chart", "kpi": "montant_ttc_par_minute"},
            {"type": "table", "kpi": "dernieres_factures"},
        ],
    },
    {
        "code": "mobile_money",
        "nom": "Mobile Money temps réel",
        "description": "Transactions Wave, OM, MTN, Moov",
        "widgets": [
            {"type": "counter", "kpi": "nb_transactions_5min"},
            {"type": "pie_chart", "kpi": "repartition_par_provider"},
            {"type": "line_chart", "kpi": "volume_par_minute"},
        ],
    },
    {
        "code": "alertes_securite",
        "nom": "Alertes sécurité",
        "description": "Anomalies comptables et fraudes détectées",
        "widgets": [
            {"type": "counter", "kpi": "nb_alertes_actives"},
            {"type": "table", "kpi": "dernieres_alertes_critiques"},
        ],
    },
    {
        "code": "system_health",
        "nom": "Santé système",
        "description": "API latency, throughput, erreurs",
        "widgets": [
            {"type": "gauge", "kpi": "latence_p95_ms"},
            {"type": "line_chart", "kpi": "requetes_par_seconde"},
            {"type": "counter", "kpi": "erreurs_5xx_5min"},
        ],
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Limitations
# ─────────────────────────────────────────────────────────────────────────────
class LimitesAnalytics:
    MAX_ALERT_RULES_PER_TENANT = 100
    MAX_DASHBOARDS_PER_TENANT = 20
    MAX_RETENTION_EVENTS_JOURS = 90
    MAX_QUERY_TIME_RANGE_JOURS = 365
    COOLDOWN_ALERTE_SECONDES = 300    # 5 min entre 2 alertes identiques
    BACKPRESSURE_THRESHOLD_MS = 5000  # Si lag > 5s → drop events non-critiques
