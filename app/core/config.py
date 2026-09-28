"""Configuration globale — chargée une fois au démarrage depuis .env."""
from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # Environnement
    ENV: str = "dev"
    APP_NAME: str = "MTech SaaS SYSCOHADA"
    API_PREFIX: str = "/api/v1"

    # Base de données
    DATABASE_URL: str = Field(..., description="postgresql+asyncpg://...")

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # JWT RS256
    JWT_PRIVATE_KEY: str
    JWT_PUBLIC_KEY: str
    JWT_ACCESS_TTL: int = 900
    JWT_REFRESH_TTL: int = 604800
    JWT_MFA_TTL: int = 300

    # Chiffrement AES-256-GCM
    ENCRYPTION_KEY: str

    # Webhooks Mobile Money
    WAVE_WEBHOOK_SECRET: str = ""
    ORANGE_WEBHOOK_SECRET: str = ""
    MTN_WEBHOOK_SECRET: str = ""
    MOOV_WEBHOOK_SECRET: str = ""

    # ─── IA / NLP ─────────────────────────────────────────────────────
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_MODEL_PREMIUM: str = "gpt-4o"
    OPENAI_TIMEOUT: int = 30
    OPENAI_MAX_RETRIES: int = 3
    NLP_MIN_CONFIDENCE: float = 0.55         # en-dessous → marquage "à vérifier"
    NLP_MAX_TOKENS: int = 1500
    NLP_TEMPERATURE: float = 0.1

    # ─── WhatsApp ─────────────────────────────────────────────────────
    WHATSAPP_PROVIDER: str = "meta"          # meta | twilio
    WHATSAPP_META_TOKEN: str = ""
    WHATSAPP_META_PHONE_ID: str = ""
    WHATSAPP_META_VERIFY_TOKEN: str = ""
    WHATSAPP_TWILIO_SID: str = ""
    WHATSAPP_TWILIO_TOKEN: str = ""
    WHATSAPP_TWILIO_FROM: str = ""

    # ─── Prévision trésorerie ─────────────────────────────────────────
    FORECAST_HORIZON_DAYS: int = 90
    FORECAST_MIN_HISTORY_DAYS: int = 30      # en-dessous → prévision "faible fiabilité"

    # Fondateur
    FOUNDER_EMAIL: str = "daniel@mtech.ci"

    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    @property
    def is_prod(self) -> bool:
        return self.ENV == "prod"

    @property
    def nlp_enabled(self) -> bool:
        return bool(self.OPENAI_API_KEY)

    @property
    def whatsapp_enabled(self) -> bool:
        if self.WHATSAPP_PROVIDER == "meta":
            return bool(self.WHATSAPP_META_TOKEN and self.WHATSAPP_META_PHONE_ID)
        if self.WHATSAPP_PROVIDER == "twilio":
            return bool(self.WHATSAPP_TWILIO_SID and self.WHATSAPP_TWILIO_TOKEN)
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
