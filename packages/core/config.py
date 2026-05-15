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

    # IBKR TWS/Gateway (read-only, never write)
    ibkr_enabled: bool = False
    ibkr_host: str = "localhost"
    ibkr_port: int = 7497
    ibkr_client_id: int = 1
    ibkr_timeout_seconds: int = 30
    ibkr_trade_history_months: int = 12
    ibkr_readonly: bool = True

    # IBKR Flex Query (historical trade import — separate from reqExecutions)
    ibkr_flex_enabled: bool = False
    ibkr_flex_token: str = ""        # never log; treat as secret
    ibkr_flex_query_id: str = ""     # the numeric Flex Query ID from IBKR Account Mgmt
    # Root URL — client appends /SendRequest and /GetStatement automatically.
    # Example: https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService
    ibkr_flex_base_url: str = (
        "https://ndcdyn.interactivebrokers.com/AccountManagement/FlexWebService"
    )
    # Override poll URL; if empty, derived as base_url + "/GetStatement".
    # Normally left blank — the <Url> element in the SendRequest response is used.
    ibkr_flex_poll_url: str = ""
    ibkr_flex_timeout_seconds: int = 60
    ibkr_flex_max_polls: int = 10
    ibkr_flex_poll_interval_seconds: int = 3

    # Ollama (local LLM — never sends data to cloud)
    ollama_enabled: bool = False
    ollama_base_url: str = "http://host.docker.internal:11434"
    ollama_model: str = "llama3.1:8b"
    ollama_timeout_seconds: int = 60

    # News
    newsapi_key: str = ""
    news_enabled: bool = False
    news_provider: str = "newsapi"
    news_lookback_days: int = 14
    news_max_articles_per_symbol: int = 20
    news_timeout_seconds: int = 20
    news_max_retries: int = 2

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
