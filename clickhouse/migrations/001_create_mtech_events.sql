-- Base de données
CREATE DATABASE IF NOT EXISTS mtech_analytics;

-- Table principale des events (MergeTree pour performance)
CREATE TABLE IF NOT EXISTS mtech_analytics.mtech_events
(
    event_id        String,
    topic           LowCardinality(String),
    partition       Int32,
    offset          Int64,
    tenant_id       String,
    event_type      LowCardinality(String),
    event_time      DateTime64(3),
    payload         String,           -- JSON brut
    inserted_at     DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_time)
ORDER BY (tenant_id, topic, event_time, event_id)
TTL event_time + INTERVAL 90 DAY
SETTINGS index_granularity = 8192;

-- Index secondaires (skip indexes)
ALTER TABLE mtech_analytics.mtech_events
    ADD INDEX idx_event_type event_type TYPE set(0) GRANULARITY 1;

-- Vue agrégée : compteur d'events par minute
CREATE MATERIALIZED VIEW IF NOT EXISTS mtech_analytics.mtech_events_per_minute
ENGINE = SummingMergeTree()
PARTITION BY toYYYYMM(ts)
ORDER BY (tenant_id, topic, ts)
AS
SELECT
    tenant_id,
    topic,
    toStartOfMinute(event_time) AS ts,
    count() AS nb_events
FROM mtech_analytics.mtech_events
GROUP BY tenant_id, topic, ts;
