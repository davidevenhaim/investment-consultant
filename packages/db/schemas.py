"""Pydantic v2 schemas for API request/response objects."""

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from db.enums import (
    AssetType,
    ResearchRunType,
    RiskLevel,
)


class _OrmBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ── Watchlist ─────────────────────────────────────────────────────────────────


class WatchlistSymbolCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    company_name: str | None = None
    exchange: str | None = None
    asset_type: AssetType = AssetType.EQUITY
    notes: str | None = None


class WatchlistSymbolResponse(_OrmBase):
    id: uuid.UUID
    symbol: str
    company_name: str | None
    exchange: str | None
    asset_type: str
    is_active: bool
    notes: str | None
    created_at: datetime
    updated_at: datetime


# ── Investor profile ──────────────────────────────────────────────────────────


class InvestorProfileUpdate(BaseModel):
    risk_level: RiskLevel | None = None
    max_single_stock_weight: float | None = Field(default=None, gt=0, le=1)
    max_new_position_weight: float | None = Field(default=None, gt=0, le=1)
    max_drawdown_tolerance: float | None = Field(default=None, gt=0, le=1)
    min_confidence_to_buy: float | None = Field(default=None, ge=0, le=1)
    investment_horizon: str | None = None


class InvestorProfileResponse(_OrmBase):
    id: uuid.UUID
    name: str
    risk_level: str
    max_single_stock_weight: float
    max_new_position_weight: float
    max_drawdown_tolerance: float
    min_confidence_to_buy: float
    allow_margin: bool
    allow_options: bool
    allow_shorting: bool
    investment_horizon: str
    is_active: bool
    created_at: datetime
    updated_at: datetime


# ── Research runs ─────────────────────────────────────────────────────────────


class ResearchRunCreate(BaseModel):
    run_type: ResearchRunType = ResearchRunType.MANUAL
    symbols: list[str] | None = Field(
        default=None,
        description="Override watchlist. If omitted, uses active watchlist.",
    )
    async_execution: bool = Field(
        default=False,
        description=(
            "If true, enqueue the run as a Celery task and return immediately with "
            "status QUEUED. If false (default), execute synchronously."
        ),
    )


class ResearchRunTickerResponse(_OrmBase):
    id: uuid.UUID
    research_run_id: uuid.UUID
    symbol: str
    status: str
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    created_at: datetime


class ResearchRunResponse(_OrmBase):
    id: uuid.UUID
    run_type: str
    status: str
    strategy_version_id: uuid.UUID | None
    prompt_version_id: uuid.UUID | None
    started_at: datetime | None
    finished_at: datetime | None
    error_message: str | None
    created_at: datetime
    tickers: list[ResearchRunTickerResponse] = []


class ResearchRunListItem(_OrmBase):
    id: uuid.UUID
    run_type: str
    status: str
    created_at: datetime
    finished_at: datetime | None
    ticker_count: int = 0


# ── Recommendations ───────────────────────────────────────────────────────────


class NeutralRecommendationResponse(_OrmBase):
    id: uuid.UUID
    research_run_id: uuid.UUID
    symbol: str
    action: str
    score: int
    confidence: float
    time_horizon: str | None
    final_reason: str
    main_reasons_json: list[Any]
    main_risks_json: list[Any]
    missing_details_json: list[Any]
    score_breakdown_json: dict[str, Any]
    as_of_time: datetime
    price_at_recommendation: float | None
    data_quality_score: float | None
    created_at: datetime


class PersonalizedRecommendationResponse(_OrmBase):
    id: uuid.UUID
    neutral_recommendation_id: uuid.UUID
    symbol: str
    personal_action: str
    personal_reason: str
    position_sizing_json: dict[str, Any]
    policy_checks_json: list[Any]
    current_position_weight: float | None
    max_allowed_weight: float | None
    portfolio_snapshot_id: uuid.UUID | None
    symbol_trading_stats_json: dict[str, Any] = {}
    created_at: datetime


class LatestRecommendationResponse(BaseModel):
    symbol: str
    neutral: NeutralRecommendationResponse | None = None
    personalized: PersonalizedRecommendationResponse | None = None


class RecommendationEvidenceResponse(_OrmBase):
    id: uuid.UUID
    recommendation_id: uuid.UUID
    recommendation_type: str
    evidence_type: str
    source: str | None
    source_id: str | None
    summary: str
    url: str | None
    published_at: datetime | None
    payload_json: dict[str, Any]
    created_at: datetime


class RunRecommendationItem(BaseModel):
    symbol: str
    neutral: NeutralRecommendationResponse | None = None
    personalized: PersonalizedRecommendationResponse | None = None
    evidence: list[RecommendationEvidenceResponse] = []


class ResearchRunRecommendationsResponse(BaseModel):
    research_run_id: uuid.UUID
    status: str
    run_type: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    recommendations: list[RunRecommendationItem] = []


# ── Portfolio ─────────────────────────────────────────────────────────────────


class PortfolioPositionCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    quantity: float = Field(gt=0)
    average_cost: float | None = Field(default=None, gt=0)


class PortfolioPositionResponse(_OrmBase):
    id: uuid.UUID
    account_id: uuid.UUID
    symbol: str
    quantity: float
    average_cost: float | None
    current_price: float | None
    market_value: float | None
    cost_basis: float | None
    unrealized_pnl: float | None
    unrealized_pnl_pct: float | None
    weight: float | None
    as_of_time: datetime
    created_at: datetime
    updated_at: datetime


class PortfolioAccountResponse(_OrmBase):
    id: uuid.UUID
    name: str
    account_type: str
    base_currency: str
    cash_balance: float
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PortfolioSnapshotResponse(_OrmBase):
    id: uuid.UUID
    account_id: uuid.UUID
    total_market_value: float
    cash_balance: float
    total_equity: float
    number_of_positions: int
    max_position_weight: float | None
    top_positions_json: list[Any]
    risk_metrics_json: dict[str, Any]
    as_of_time: datetime
    created_at: datetime


class PortfolioSummaryResponse(BaseModel):
    account: PortfolioAccountResponse
    snapshot: PortfolioSnapshotResponse | None
    positions: list[PortfolioPositionResponse]


# ── Broker accounts ───────────────────────────────────────────────────────────

_FORBIDDEN_BODY_KEYS = {"password", "username", "secret", "token", "api_key", "apikey"}


class BrokerAccountCreate(BaseModel):
    provider: Literal["IBKR"] = "IBKR"
    display_name: str = Field(min_length=1, max_length=255)
    connection_mode: Literal["LOCAL_TWS", "HOSTED_GATEWAY"] = "LOCAL_TWS"
    host: str | None = None
    port: int | None = Field(default=None, gt=0, lt=65536)
    client_id: int = Field(default=1, gt=0)
    readonly: Literal[True] = True  # must always be True
    is_active: bool = True
    external_account_id: str | None = None
    metadata_json: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any) -> None:
        for key in _FORBIDDEN_BODY_KEYS:
            if key in self.metadata_json:
                raise ValueError(
                    f"metadata_json must not contain '{key}'. "
                    "Store secret references (e.g. secret_ref) instead."
                )


class BrokerAccountUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    connection_mode: Literal["LOCAL_TWS", "HOSTED_GATEWAY"] | None = None
    host: str | None = None
    port: int | None = Field(default=None, gt=0, lt=65536)
    client_id: int | None = Field(default=None, gt=0)
    is_active: bool | None = None
    metadata_json: dict[str, Any] | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.metadata_json:
            for key in _FORBIDDEN_BODY_KEYS:
                if key in self.metadata_json:
                    raise ValueError(
                        f"metadata_json must not contain '{key}'. "
                        "Store secret references (e.g. secret_ref) instead."
                    )


class BrokerAccountResponse(_OrmBase):
    id: uuid.UUID
    provider: str
    display_name: str
    connection_mode: str
    host: str | None
    port: int | None
    client_id: int
    readonly: bool
    is_active: bool
    external_account_id: str | None
    last_sync_at: datetime | None
    last_sync_status: str | None
    metadata_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


# ── Trade history ─────────────────────────────────────────────────────────────


class ManualTradeCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=20)
    side: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    executed_at: datetime
    notes: str | None = None
    source: str = "manual"


class ManualTradeResponse(_OrmBase):
    id: uuid.UUID
    symbol: str
    side: str
    quantity: float
    price: float
    executed_at: datetime
    notes: str | None
    source: str
    created_at: datetime
    updated_at: datetime


class IBKRExecutionResponse(_OrmBase):
    id: uuid.UUID
    account_id_ibkr: str
    exec_id: str
    symbol: str
    exchange: str | None
    side: str
    quantity: float
    price: float
    commission: float | None
    currency: str
    executed_at: datetime
    order_ref: str | None
    created_at: datetime


class TradingProfileResponse(_OrmBase):
    id: uuid.UUID
    period_months: int
    as_of_date: datetime
    total_executions: int
    total_symbols_traded: int
    win_rate: float | None
    avg_winner_pct: float | None
    avg_loser_pct: float | None
    profit_factor: float | None
    avg_holding_days: float | None
    disposition_effect_score: float | None
    concentration_score: float | None
    recency_bias_score: float | None
    behavioral_flags_json: list[Any]
    per_symbol_stats_json: dict[str, Any]
    raw_metrics_json: dict[str, Any]
    created_at: datetime


class IBKRSyncResponse(BaseModel):
    inserted: int
    message: str


# ── Backtesting (M11) ─────────────────────────────────────────────────────────


class RecommendationOutcomeResponse(_OrmBase):
    id: uuid.UUID
    recommendation_type: str
    recommendation_id: uuid.UUID
    research_run_id: uuid.UUID | None
    symbol: str
    action: str
    score: int | None
    price_at_recommendation: float | None
    measured_from: datetime
    measured_to: datetime
    horizon_days: int
    benchmark_symbol: str | None
    start_price: float | None
    end_price: float | None
    benchmark_start_price: float | None
    benchmark_end_price: float | None
    forward_return_pct: float | None
    benchmark_return_pct: float | None
    relative_return_pct: float | None
    max_drawdown_pct: float | None
    max_runup_pct: float | None
    outcome_status: str
    outcome_label: str | None
    created_at: datetime
    updated_at: datetime


class LearningEventResponse(_OrmBase):
    id: uuid.UUID
    recommendation_outcome_id: uuid.UUID | None
    research_run_id: uuid.UUID | None
    symbol: str
    event_type: str
    severity: str
    title: str
    summary: str
    suspected_causes_json: list[Any]
    evidence_json: dict[str, Any]
    suggested_adjustments_json: list[Any]
    status: str
    created_at: datetime
    updated_at: datetime


class MeasureOutcomesRequest(BaseModel):
    horizon_days: int = Field(default=30, ge=1, le=365)
    benchmark_symbol: str = Field(default="SPY", min_length=1, max_length=20)


class LearningEventStatusUpdate(BaseModel):
    status: Literal["REVIEWED", "DISMISSED", "APPLIED"]


# ── Advisor Backtest (M11.1) ──────────────────────────────────────────────────

import datetime as _dt  # noqa: E402


class AdvisorBacktestRequest(BaseModel):
    start_date: _dt.date
    end_date: _dt.date
    initial_cash: float = Field(gt=0)
    benchmark_symbol: str = Field(default="SPY", min_length=1, max_length=20)
    name: str | None = None
    recommendation_source: Literal["ALL", "SCENARIO", "REAL"] = "ALL"
    scenario_name: str | None = None

    def model_post_init(self, __context: Any) -> None:
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if self.scenario_name is not None and self.recommendation_source != "SCENARIO":
            raise ValueError(
                "scenario_name is only valid when recommendation_source is 'SCENARIO'"
            )


class AdvisorBacktestRunResponse(_OrmBase):
    id: uuid.UUID
    name: str | None
    start_date: _dt.date
    end_date: _dt.date
    initial_cash: float
    final_equity: float | None
    cash_final: float | None
    total_return_pct: float | None
    benchmark_symbol: str | None
    benchmark_return_pct: float | None
    relative_return_pct: float | None
    max_drawdown_pct: float | None
    total_trades: int
    winning_trades: int
    losing_trades: int
    status: str
    summary_json: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class AdvisorBacktestTradeResponse(_OrmBase):
    id: uuid.UUID
    symbol: str
    action: str
    trade_type: str
    trade_date: datetime
    price: float | None
    quantity: float | None
    cash_delta: float | None
    position_before: float | None
    position_after: float | None
    reason: str | None


class AdvisorBacktestEquityPointResponse(_OrmBase):
    date: _dt.date
    equity: float
    cash: float
    positions_value: float
    drawdown_pct: float | None
    benchmark_value: float | None


class AdvisorBacktestRunDetailResponse(_OrmBase):
    id: uuid.UUID
    name: str | None
    start_date: _dt.date
    end_date: _dt.date
    initial_cash: float
    final_equity: float | None
    total_return_pct: float | None
    benchmark_symbol: str | None
    benchmark_return_pct: float | None
    relative_return_pct: float | None
    max_drawdown_pct: float | None
    total_trades: int
    winning_trades: int
    losing_trades: int
    status: str
    summary_json: dict[str, Any]
    assumptions_json: dict[str, Any]
    created_at: datetime
    trades: list[AdvisorBacktestTradeResponse] = []
    equity_points: list[AdvisorBacktestEquityPointResponse] = []


# ── Advisor Backtest Analysis (M11.3) ─────────────────────────────────────────


class AdvisorBacktestAnalysisRequest(BaseModel):
    force: bool = False


class AdvisorBacktestAnalysisResponse(_OrmBase):
    id: uuid.UUID
    advisor_backtest_run_id: uuid.UUID
    provider: str
    model: str
    prompt_version: str
    status: str
    analysis_json: dict[str, Any]
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    # user_id intentionally not exposed
