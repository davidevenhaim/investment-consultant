from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Database
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/investment"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # ChromaDB
    chroma_host: str = "localhost"
    chroma_port: int = 8001

    # Anthropic / LLM
    anthropic_api_key: str = ""
    llm_enabled: bool = False
    llm_model: str = "claude-sonnet-4-20250514"
    llm_timeout_seconds: int = 30
    llm_max_retries: int = 2

    # IBKR (read-only, never write)
    ibkr_host: str = "localhost"
    ibkr_port: int = 7497
    ibkr_client_id: int = 1

    # News
    newsapi_key: str = ""

    # App
    environment: Literal["development", "staging", "production", "test"] = "development"
    log_level: str = "INFO"
    secret_key: str = Field(default="dev-secret-key-change-in-production")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def chroma_url(self) -> str:
        return f"http://{self.chroma_host}:{self.chroma_port}"


@lru_cache
def get_settings() -> Settings:
    return Settings()
