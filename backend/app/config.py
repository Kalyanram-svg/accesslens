"""Application configuration. All secrets and model names come from the environment."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "NovaTech Compliance Intelligence"
    environment: str = "demo"  # demo | production
    demo_mode: bool = True

    database_url: str = "postgresql+psycopg://postgres@localhost:5432/novatech"
    redis_url: str | None = None

    jwt_secret: str = "change-me-in-env"  # overridden by JWT_SECRET
    jwt_algorithm: str = "HS256"
    session_ttl_minutes: int = 480

    # --- AI / model routing (never hardcode model names in business logic) ---
    openai_api_key: str | None = None
    openai_model: str | None = None  # reasoning-capable model for analysis/orchestration
    openai_fast_model: str | None = None  # cheap model for intent classification
    openai_embedding_model: str | None = None
    embedding_provider: str = "hash"  # hash | openai
    embedding_dim: int = 256

    # --- Storage ---
    storage_bucket: str | None = None
    storage_endpoint: str | None = None
    storage_access_key: str | None = None
    storage_secret_key: str | None = None
    local_storage_dir: str = "./storage"

    # --- Agent behaviour ---
    demo_step_delay_ms: int = 350  # pacing so judges can follow the live activity panel
    rate_limit_per_minute: int = 60
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def llm_enabled(self) -> bool:
        return bool(self.openai_api_key and self.openai_model)

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")


@lru_cache
def get_settings() -> Settings:
    return Settings()
