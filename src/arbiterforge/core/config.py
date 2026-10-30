from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_TOKEN_SECRET = "dev-only-token-secret-change-me"
DEV_AUDIT_SECRET = "dev-only-audit-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ARBITERFORGE_",
        case_sensitive=False,
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"
    host: str = "127.0.0.1"
    port: int = 8023
    log_json: bool = True
    log_masking: bool = True

    database_url: str = "postgresql+asyncpg://arbiterforge:arbiterforge@localhost:5423/arbiterforge"
    redis_url: str = "redis://localhost:6323/0"
    celery_broker_url: str | None = None
    event_stream: str = "arbiterforge:events"
    event_stream_maxlen: int = 100_000
    relay_batch_size: int = 500
    relay_interval_seconds: float = 5.0

    token_secret: SecretStr = SecretStr(DEV_TOKEN_SECRET)
    audit_hmac_secret: SecretStr = SecretStr(DEV_AUDIT_SECRET)
    access_token_ttl_minutes: int = 60

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:7b"
    ollama_timeout_seconds: float = 30.0

    cors_allow_origins: str = "http://localhost:8023"

    @model_validator(mode="after")
    def _forbid_dev_secrets_in_prod(self) -> Settings:
        if self.env == "prod" and (
            self.token_secret.get_secret_value() == DEV_TOKEN_SECRET
            or self.audit_hmac_secret.get_secret_value() == DEV_AUDIT_SECRET
        ):
            raise ValueError("Set ARBITERFORGE_TOKEN_SECRET and ARBITERFORGE_AUDIT_HMAC_SECRET")
        return self

    @property
    def broker_url(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.cors_allow_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
