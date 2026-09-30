CREATE TABLE IF NOT EXISTS mtech_analytics.mtech_alerts
(
    alert_id        String,
    tenant_id       String,
    rule_code       LowCardinality(String),
    severite        LowCardinality(String),
    titre           String,
    event_time      DateTime64(3),
    payload         String,
    inserted_at     DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(event_time)
ORDER BY (tenant_id, severite, event_time)
TTL event_time + INTERVAL 365 DAY;
