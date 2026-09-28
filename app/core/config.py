from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True)

    ENV: str = "dev"
    DATABASE_URL: str
    REDIS_URL: str
    JWT_PRIVATE_KEY: str
    JWT_PUBLIC_KEY: str
    JWT_ACCESS_TTL: int = 900          # 15 min
    JWT_REFRESH_TTL: int = 604800      # 7 jours

    WAVE_WEBHOOK_SECRET: str
    ORANGE_WEBHOOK_SECRET: str
    MTN_WEBHOOK_SECRET: str
    OPENAI_API_KEY: str

    ENCRYPTION_KEY: str                # AES-256 (32 bytes base64)
    FOUNDER_EMAIL: str                 # ⚠️ pour create_founder.py

settings = Settings()
