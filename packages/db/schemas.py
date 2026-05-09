"""Pydantic v2 schemas for API request/response objects."""

import uuid
from datetime import datetime
from typing import Any

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
    as_of_time: datetime
    price_at_recommendation: float | None
    data_quality_score: float | None
    created_at: datetime


class LatestRecommendationResponse(BaseModel):
    symbol: str
    neutral: NeutralRecommendationResponse | None = None
