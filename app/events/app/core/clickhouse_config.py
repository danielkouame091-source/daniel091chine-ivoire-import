"""Configuration ClickHouse — client async (clickhouse-connect)."""
from __future__ import annotations

from pydantic_settings import BaseSettings


class ClickHouseSettings(BaseSettings):
    CLICKHOUSE_HOST: str = "localhost"
    CLICKHOUSE_PORT: int = 8123
    CLICKHOUSE_USER: str = "default"
    CLICKHOUSE_PASSWORD: str = ""
    CLICKHOUSE_DATABASE: str = "mtech_analytics"
    CLICKHOUSE_SECURE: bool = False

    # Pool & performance
    CLICKHOUSE_POOL_SIZE: int = 10
    CLICKHOUSE_QUERY_TIMEOUT: int = 30
    CLICKHOUSE_ASYNC_INSERT: bool = True
    CLICKHOUSE_WAIT_ASYNC_INSERT: bool = False
    CLICKHOUSE_MAX_INSERT_SIZE: int = 10_000_000  # 10 MB

    model_config = {"env_file": ".env", "extra": "ignore"}


clickhouse_settings = ClickHouseSettings()
