from typing import Any


class InvestmentConsultantError(Exception):
    """Base exception for all application errors."""

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, detail: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail or {}


# ── Resource errors ──────────────────────────────────────────────────────────


class NotFoundError(InvestmentConsultantError):
    status_code = 404
    error_code = "NOT_FOUND"


class ConflictError(InvestmentConsultantError):
    status_code = 409
    error_code = "CONFLICT"


# ── Validation errors ─────────────────────────────────────────────────────────


class ValidationError(InvestmentConsultantError):
    status_code = 422
    error_code = "VALIDATION_ERROR"


# ── External service errors ───────────────────────────────────────────────────


class ExternalServiceError(InvestmentConsultantError):
    """Base for errors from external services. Always log, never crash a run."""

    status_code = 503
    error_code = "EXTERNAL_SERVICE_ERROR"


class DatabaseError(ExternalServiceError):
    error_code = "DATABASE_ERROR"


class RedisError(ExternalServiceError):
    error_code = "REDIS_ERROR"


class ChromaError(ExternalServiceError):
    error_code = "CHROMA_ERROR"


class LLMError(ExternalServiceError):
    error_code = "LLM_ERROR"


class LLMParseError(LLMError):
    """LLM returned output that failed Pydantic validation."""

    error_code = "LLM_PARSE_ERROR"


class MarketDataError(ExternalServiceError):
    error_code = "MARKET_DATA_ERROR"


class MemoryStoreError(ExternalServiceError):
    error_code = "MEMORY_STORE_ERROR"


class FundamentalsDataError(ExternalServiceError):
    error_code = "FUNDAMENTALS_DATA_ERROR"


class NewsAPIError(ExternalServiceError):
    error_code = "NEWS_API_ERROR"


class IBKRError(ExternalServiceError):
    error_code = "IBKR_ERROR"


# ── Research run errors ───────────────────────────────────────────────────────


class ResearchRunError(InvestmentConsultantError):
    error_code = "RESEARCH_RUN_ERROR"


class RunAlreadyActiveError(ResearchRunError):
    status_code = 409
    error_code = "RUN_ALREADY_ACTIVE"
