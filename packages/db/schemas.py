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
    created_at: datetime


class LatestRecommendationResponse(BaseModel):
    symbol: str
    neutral: NeutralRecommendationResponse | None = None
    personalized: PersonalizedRecommendationResponse | None = None


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
