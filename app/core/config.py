from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    api_key: str = Field(default="change-me", alias="API_KEY")
    database_url: str = Field(
        default="postgresql+asyncpg://payments:payments@localhost:5432/payments",
        alias="DATABASE_URL",
    )
    rabbitmq_url: str = Field(
        default="amqp://guest:guest@localhost:5672/",
        alias="RABBITMQ_URL",
    )

    outbox_poll_interval_seconds: float = Field(
        default=1.0,
        alias="OUTBOX_POLL_INTERVAL_SECONDS",
        gt=0,
    )
    outbox_batch_size: int = Field(default=50, alias="OUTBOX_BATCH_SIZE", gt=0)

    payment_processing_min_seconds: float = Field(
        default=2.0,
        alias="PAYMENT_PROCESSING_MIN_SECONDS",
        ge=0,
    )
    payment_processing_max_seconds: float = Field(
        default=5.0,
        alias="PAYMENT_PROCESSING_MAX_SECONDS",
        ge=0,
    )
    payment_success_rate: float = Field(
        default=0.9,
        alias="PAYMENT_SUCCESS_RATE",
        ge=0,
        le=1,
    )

    webhook_timeout_seconds: float = Field(
        default=5.0,
        alias="WEBHOOK_TIMEOUT_SECONDS",
        gt=0,
    )
    webhook_retry_attempts: int = Field(
        default=3,
        alias="WEBHOOK_RETRY_ATTEMPTS",
        ge=1,
    )

    max_processing_attempts: int = Field(
        default=3,
        alias="MAX_PROCESSING_ATTEMPTS",
        ge=1,
    )

    @property
    def payment_processing_delay_range(self) -> tuple[float, float]:
        low = self.payment_processing_min_seconds
        high = max(low, self.payment_processing_max_seconds)
        return low, high


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
