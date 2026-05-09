from enum import StrEnum


class ResearchRunType(StrEnum):
    MANUAL = "MANUAL"
    MORNING = "MORNING"
    EVENING = "EVENING"
    BACKTEST = "BACKTEST"


class ResearchRunStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TickerRunStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class RecommendationAction(StrEnum):
    STRONG_BUY = "STRONG_BUY"
    BUY_CANDIDATE = "BUY_CANDIDATE"
    HOLD = "HOLD"
    REDUCE = "REDUCE"
    SELL = "SELL"
    WATCHLIST = "WATCHLIST"
    NO_ACTION = "NO_ACTION"


class RecommendationType(StrEnum):
    NEUTRAL = "NEUTRAL"
    PERSONALIZED = "PERSONALIZED"


class EvidenceType(StrEnum):
    MARKET_DATA = "MARKET_DATA"
    NEWS = "NEWS"
    FILING = "FILING"
    MEMORY = "MEMORY"
    TECHNICAL_SIGNAL = "TECHNICAL_SIGNAL"
    POLICY_CHECK = "POLICY_CHECK"
    MANUAL_NOTE = "MANUAL_NOTE"
    LLM_ANALYSIS = "LLM_ANALYSIS"
    NEWS_ANALYSIS = "NEWS_ANALYSIS"
    NEWS_ITEM = "NEWS_ITEM"


class AssetType(StrEnum):
    EQUITY = "EQUITY"
    ETF = "ETF"
    CRYPTO = "CRYPTO"


class RiskLevel(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
