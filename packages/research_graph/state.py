"""ResearchState TypedDict and all Pydantic state models used by graph nodes.

These Pydantic models are the graph's internal typed outputs — they are distinct from
the SQLAlchemy DB models in packages/db/models.py.
"""

import operator
from datetime import datetime
from typing import Annotated, Any

from db.enums import RecommendationAction
from pydantic import BaseModel, Field

# ── Pydantic output models ────────────────────────────────────────────────────


class ScoreBreakdown(BaseModel):
    technical_score: float = 0.0
    fundamental_score: float = 0.0
    valuation_score: float = 0.0
    news_score: float = 0.0  # stub until M8
    portfolio_fit_score: float = 0.0  # stub until M9
    risk_score: float = 0.0
    total_score: float = 0.0
    # M5 completeness metadata
    recommendation_scope: str = "UNKNOWN"
    analysis_completeness_score: float = 0.0
    completed_components: list[str] = []
    missing_components: list[str] = []
    component_quality_scores: dict[str, float] = {}
    # M7 LLM metadata
    llm_enabled: bool = False
    llm_model: str | None = None
    llm_analysis_quality: float = 0.0
    llm_confidence_penalty: float = 0.0
    critic_should_cap_strong_buy: bool = False
    thesis_alignment: str = "NO_PREVIOUS_THESIS"
    strongest_counterargument: str = ""
    llm_warnings: list[str] = []


class NeutralRecState(BaseModel):
    """Neutral recommendation produced by the deterministic scoring engine."""

    action: RecommendationAction
    score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    final_reason: str
    score_breakdown: ScoreBreakdown
    main_reasons: list[str] = []
    main_risks: list[str] = []
    missing_details: list[str] = []
    data_quality_score: float = Field(default=1.0, ge=0.0, le=1.0)


class PersonalizedRecState(BaseModel):
    """Portfolio-aware recommendation produced by the risk policy engine."""

    personal_action: RecommendationAction
    personal_reason: str
    policy_checks: list[dict[str, Any]] = []
    current_position_weight: float = 0.0
    max_allowed_weight: float = 0.15


# ── Stub models for future milestones ────────────────────────────────────────


class NewsAnalysis(BaseModel):
    """Populated in M8 (LLM news analysis)."""

    sentiment_score: float = 0.0
    key_events: list[str] = []
    risk_events: list[str] = []
    what_changed: str = ""
    confidence: float = 0.0


class ThesisComparison(BaseModel):
    """Populated in M7 (LLM thesis comparison)."""

    thesis_drift: bool = False
    what_changed: str = ""
    confidence: float = 0.0


class MissingDetailsResult(BaseModel):
    """Populated in M7 (LLM missing details check)."""

    missing_details: list[str] = []
    severity: str = "LOW"
    can_continue: bool = True
    confidence_penalty: float = 0.0


class BullBearCase(BaseModel):
    """Populated in M7 (LLM bull/bear narrative)."""

    bull_case: str = ""
    bear_case: str = ""
    confidence: float = 0.0


class PortfolioSnapshotState(BaseModel):
    """Populated in M9 (IBKR portfolio snapshot)."""

    positions: dict[str, float] = {}  # symbol → portfolio weight
    cash_weight: float = 1.0
    total_value_usd: float = 0.0


# ── Main state ────────────────────────────────────────────────────────────────


from typing import TypedDict  # noqa: E402


class ResearchState(TypedDict):
    # ── run context ──────────────────────────────────────────────────────────
    run_id: str
    run_ticker_id: str  # UUID of the ResearchRunTicker DB record (M3 addition)
    symbol: str
    as_of_time: datetime
    strategy_version: str
    prompt_version: str
    strategy_config: dict[str, Any]  # scoring config loaded from strategy_versions table

    # ── LLM analysis (M7+) ──────────────────────────────────────────────────
    llm_analysis: Any  # CombinedLLMAnalysis | None — deferred import
    llm_warnings: Annotated[list[str], operator.add]
    llm_confidence_penalty: float

    # ── retrieved memory (M6+) ───────────────────────────────────────────────
    memory_context: Any  # MemoryContext | None — deferred import
    memory_count: int
    memory_summary: str | None
    previous_thesis: str | None
    last_recommendation: dict[str, Any] | None
    past_mistakes: list[dict[str, Any]]

    # ── market data (mock in M3; real yfinance in M4) ────────────────────────
    ohlcv: Any  # pd.DataFrame | None — pandas import deferred to avoid type noise
    technical_signals: dict[str, Any] | None

    # ── news (M8+) ───────────────────────────────────────────────────────────
    news_items: list[dict[str, Any]]
    news_analysis: NewsAnalysis | None

    # ── LLM outputs (M7+) ───────────────────────────────────────────────────
    thesis_comparison: ThesisComparison | None
    missing_details: MissingDetailsResult | None
    bull_bear_case: BullBearCase | None

    # ── fundamentals (M5+) ──────────────────────────────────────────────────
    fundamentals_snapshot: Any  # CompanyFundamentalsSnapshot | None — deferred import
    fundamentals_data_quality: float

    # ── scoring ──────────────────────────────────────────────────────────────
    score_breakdown: ScoreBreakdown | None
    neutral_rec: NeutralRecState | None  # named to avoid clash with db.models.NeutralRecommendation

    # ── analysis completeness ────────────────────────────────────────────────
    analysis_completeness: float
    completed_components: list[str]
    missing_components: list[str]

    # ── portfolio (M9+) ──────────────────────────────────────────────────────
    portfolio_snapshot: PortfolioSnapshotState | None
    personalized_rec: PersonalizedRecState | None

    # ── errors + quality ─────────────────────────────────────────────────────
    # Annotated with operator.add so nodes append rather than replace.
    errors: Annotated[list[str], operator.add]
    data_quality_score: float
    confidence_penalties: Annotated[list[float], operator.add]
