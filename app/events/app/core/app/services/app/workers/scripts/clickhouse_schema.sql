-- =============================================================================
-- MTech Analytics — Schéma ClickHouse
-- =============================================================================
CREATE DATABASE IF NOT EXISTS mtech_analytics;

-- ─── ÉVÉNEMENTS FACTURES ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mtech_analytics.events_invoices
(
    event_id      UUID,
    event_type    LowCardinality(String),
    tenant_id     String,
    timestamp     DateTime64(3),
    source        LowCardinality(String),
    invoice_id    UUID,
    numero        String,
    total_ttc     Int64,
    customer_id   Nullable(String),
    montant       Int64 DEFAULT 0,
    amount        Int64 DEFAULT 0
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (tenant_id, timestamp)
TTL toDateTime(timestamp) + INTERVAL 24 MONTH
SETTINGS index_granularity = 8192, ttl_only_drop_parts = 1;

-- ─── PAIEMENTS ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mtech_analytics.events_payments
(
    event_id      UUID,
    event_type    LowCardinality(String),
    tenant_id     String,
    timestamp     DateTime64(3),
    payment_id    UUID,
    montant       Int64,
    mode          LowCardinality(String),
    invoice_id    Nullable(String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (tenant_id, timestamp)
TTL toDateTime(timestamp) + INTERVAL 24 MONTH
SETTINGS ttl_only_drop_parts = 1;

-- ─── MOBILE MONEY ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mtech_analytics.events_mm_transactions
(
    event_id      UUID,
    tenant_id     String,
    timestamp     DateTime64(3),
    provider      LowCardinality(String),
    montant       Int64,
    amount        Int64 DEFAULT 0,
    sens          LowCardinality(String),
    external_id   String
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (tenant_id, provider, timestamp)
TTL toDateTime(timestamp) + INTERVAL 24 MONTH
SETTINGS ttl_only_drop_parts = 1;

-- ─── AUDIT FINDINGS ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mtech_analytics.events_audit_findings
(
    event_id      UUID,
    tenant_id     String,
    timestamp     DateTime64(3),
    finding_id    UUID,
    severite      LowCardinality(String),
    regle         LowCardinality(String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (tenant_id, severite, timestamp)
TTL toDateTime(timestamp) + INTERVAL 24 MONTH;

-- ─── ÉCRITURES ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mtech_analytics.events_ecritures
(
    event_id      UUID,
    tenant_id     String,
    timestamp     DateTime64(3),
    ecriture_id   UUID,
    numero_piece  String,
    montant_total_xof Int64,
    journal       LowCardinality(String),
    source        LowCardinality(String)
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (tenant_id, journal, timestamp)
TTL toDateTime(timestamp) + INTERVAL 24 MONTH;

-- ─── STOCK LOW ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS mtech_analytics.events_stock_low
(
    event_id      UUID,
    tenant_id     String,
    timestamp     DateTime64(3),
    item_code     String,
    quantite      Int32,
    seuil         Int32
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(timestamp)
ORDER BY (tenant_id, timestamp)
TTL toDateTime(timestamp) + INTERVAL 12 MONTH;

-- ─── VUE MATÉRIALISÉE : CA PAR HEURE ────────────────────────────────────────
CREATE MATERIALIZED VIEW IF NOT EXISTS mtech_analytics.mv_ca_horaire
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(heure)
ORDER BY (tenant_id, heure)
AS SELECT
    tenant_id,
    toStartOfHour(timestamp) AS heure,
    sum(total_ttc) AS ca_total,
    count() AS nb_factures
FROM mtech_analytics.events_invoices
WHERE event_type = 'invoice.created'
GROUP BY tenant_id, heure;

-- ─── VUE MATÉRIALISÉE : MM PAR HEURE ────────────────────────────────────────
CREATE MATERIALIZED VIEW IF NOT EXISTS mtech_analytics.mv_mm_horaire
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(heure)
ORDER BY (tenant_id, provider, heure)
AS SELECT
    tenant_id,
    provider,
    toStartOfHour(timestamp) AS heure,
    sumIf(montant, sens = 'credit') AS entrees,
    sumIf(montant, sens = 'debit') AS sorties,
    count() AS nb_transactions
FROM mtech_analytics.events_mm_transactions
GROUP BY tenant_id, provider, heure;
