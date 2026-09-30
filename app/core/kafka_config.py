"""
Configuration Kafka — Producer + Consumer asynchrones.
Bibliothèque : aiokafka (asyncio natif).
"""
from __future__ import annotations

from pydantic_settings import BaseSettings


class KafkaSettings(BaseSettings):
    KAFKA_BOOTSTRAP_SERVERS: str = "localhost:9092"
    KAFKA_CLIENT_ID: str = "mtech-analytics"
    KAFKA_GROUP_ID: str = "mtech-analytics-consumers"

    # Producer
    KAFKA_PRODUCER_ACKS: str = "all"
    KAFKA_PRODUCER_RETRIES: int = 5
    KAFKA_PRODUCER_LINGER_MS: int = 20
    KAFKA_PRODUCER_BATCH_SIZE: int = 16384
    KAFKA_PRODUCER_COMPRESSION: str = "gzip"
    KAFKA_PRODUCER_IDEMPOTENT: bool = True

    # Consumer
    KAFKA_CONSUMER_AUTO_OFFSET_RESET: str = "earliest"
    KAFKA_CONSUMER_MAX_POLL_RECORDS: int = 500
    KAFKA_CONSUMER_SESSION_TIMEOUT_MS: int = 30000
    KAFKA_CONSUMER_HEARTBEAT_INTERVAL_MS: int = 10000
    KAFKA_CONSUMER_ENABLE_AUTO_COMMIT: bool = False

    # Sécurité (SASL/SSL en production)
    KAFKA_SECURITY_PROTOCOL: str = "PLAINTEXT"
    KAFKA_SASL_MECHANISM: str | None = None
    KAFKA_SASL_USERNAME: str | None = None
    KAFKA_SASL_PASSWORD: str | None = None

    model_config = {"env_file": ".env", "extra": "ignore"}


kafka_settings = KafkaSettings()
