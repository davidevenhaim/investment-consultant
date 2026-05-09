"""All SQLAlchemy ORM models for the investment research system."""

import datetime as dt
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import TIMESTAMP as PGTIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db.base import Base, TimestampMixin, UUIDMixin
from db.enums import AssetType, ResearchRunStatus, RiskLevel, TickerRunStatus

__all__ = [
    "MarketPrice",
    "CompanyFundamentals",
    "NewsItem",
    "MemoryIndexEvent",
    "StrategyVersion",
    "PromptVersion",
    "WatchlistSymbol",
    "InvestorProfile",
    "ResearchRun",
    "ResearchRunTicker",
    "NeutralRecommendation",
    "PersonalizedRecommendation",
    "RecommendationEvidence",
    "JobEvent",
    "AuditLog",
]


class MarketPrice(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "market_prices"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "price_date",
            "provider",
            name="uq_market_price_symbol_date_provider",
        ),
        Index("ix_market_prices_symbol_date", "symbol", "price_date"),
        Index("ix_market_prices_symbol", "symbol"),
        Index("ix_market_prices_date", "price_date"),
    )

    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    price_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    open: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False)
    high: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False)
    low: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False)
    close: Mapped[float] = mapped_column(Numeric(15, 4), nullable=False)
    adjusted_close: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="yfinance")


class CompanyFundamentals(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "company_fundamentals"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "as_of_date",
            "provider",
            name="uq_company_fundamentals_symbol_date_provider",
        ),
        Index("ix_company_fundamentals_symbol_date", "symbol", "as_of_date"),
        Index("ix_company_fundamentals_symbol", "symbol"),
        Index("ix_company_fundamentals_date", "as_of_date"),
        Index("ix_company_fundamentals_provider", "provider"),
    )

    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    as_of_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="yfinance")
    market_cap: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    trailing_pe: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    forward_pe: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    price_to_book: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    price_to_sales: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    enterprise_to_revenue: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    enterprise_to_ebitda: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    revenue_growth: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    earnings_growth: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    profit_margins: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    gross_margins: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    operating_margins: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    return_on_equity: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    debt_to_equity: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    current_ratio: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    free_cashflow: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    total_cash: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    total_debt: Mapped[float | None] = mapped_column(Numeric(20, 2), nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class NewsItem(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "news_items"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "provider", "provider_article_id",
            name="uq_news_symbol_provider_article",
        ),
        Index("ix_news_items_symbol", "symbol"),
        Index("ix_news_items_published_at", "published_at"),
        Index("ix_news_items_provider", "provider"),
    )

    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_article_id: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_name: Mapped[str] = mapped_column(String(200), nullable=False)
    author: Mapped[str | None] = mapped_column(String(200), nullable=True)
    published_at: Mapped[datetime] = mapped_column(PGTIMESTAMP(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(PGTIMESTAMP(timezone=True), nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    importance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class StrategyVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "strategy_versions"

    version: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scoring_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    risk_policy_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # TODO: enforce at DB level with partial unique index:
    #   CREATE UNIQUE INDEX uq_one_active_strategy
    #   ON strategy_versions (is_active) WHERE is_active = true
    # Currently enforced in StrategyVersionRepository.activate().


class PromptVersion(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("name", "version", name="uq_prompt_name_version"),)

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    prompt_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_schema_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class WatchlistSymbol(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "watchlist_symbols"

    symbol: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(20), nullable=True)
    asset_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AssetType.EQUITY.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class InvestorProfile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "investor_profiles"

    name: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    risk_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default=RiskLevel.MEDIUM.value
    )
    max_single_stock_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.15)
    max_new_position_weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.05)
    max_drawdown_tolerance: Mapped[float] = mapped_column(Float, nullable=False, default=0.25)
    min_confidence_to_buy: Mapped[float] = mapped_column(Float, nullable=False, default=0.65)
    allow_margin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_options: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    allow_shorting: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    investment_horizon: Mapped[str] = mapped_column(
        String(30), nullable=False, default="3-12_MONTHS"
    )
    extra_config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class ResearchRun(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "research_runs"
    __table_args__ = (
        Index("ix_research_runs_status", "status"),
        Index("ix_research_runs_run_type", "run_type"),
        Index("ix_research_runs_created_at", "created_at"),
    )

    run_type: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=ResearchRunStatus.CREATED.value
    )
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("strategy_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(PGTIMESTAMP(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(PGTIMESTAMP(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    tickers: Mapped[list["ResearchRunTicker"]] = relationship(
        "ResearchRunTicker", back_populates="run", cascade="all, delete-orphan"
    )
    strategy_version: Mapped["StrategyVersion | None"] = relationship("StrategyVersion")
    prompt_version: Mapped["PromptVersion | None"] = relationship("PromptVersion")


class ResearchRunTicker(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "research_run_tickers"
    __table_args__ = (
        UniqueConstraint("research_run_id", "symbol", name="uq_run_ticker_symbol"),
        Index("ix_run_tickers_run_id", "research_run_id"),
        Index("ix_run_tickers_symbol", "symbol"),
        Index("ix_run_tickers_status", "status"),
    )

    research_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("research_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default=TickerRunStatus.CREATED.value
    )
    started_at: Mapped[datetime | None] = mapped_column(PGTIMESTAMP(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(PGTIMESTAMP(timezone=True), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    run: Mapped["ResearchRun"] = relationship("ResearchRun", back_populates="tickers")


class NeutralRecommendation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "neutral_recommendations"
    __table_args__ = (
        CheckConstraint("score >= 0 AND score <= 100", name="chk_neutral_rec_score"),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0", name="chk_neutral_rec_confidence"
        ),
        CheckConstraint(
            "data_quality_score IS NULL OR"
            " (data_quality_score >= 0.0 AND data_quality_score <= 1.0)",
            name="chk_neutral_rec_dq",
        ),
        Index("ix_neutral_rec_symbol", "symbol"),
        Index("ix_neutral_rec_action", "action"),
        Index("ix_neutral_rec_as_of_time", "as_of_time"),
        Index("ix_neutral_rec_run_id", "research_run_id"),
    )

    research_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("research_runs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    research_run_ticker_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("research_run_tickers.id", ondelete="SET NULL"),
        nullable=True,
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    time_horizon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    score_breakdown_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    what_changed_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    main_reasons_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    main_risks_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    missing_details_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    final_reason: Mapped[str] = mapped_column(Text, nullable=False)
    strategy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("strategy_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    prompt_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("prompt_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    as_of_time: Mapped[datetime] = mapped_column(PGTIMESTAMP(timezone=True), nullable=False)
    # Populated from market_prices table in M4. Do not call yfinance directly here.
    price_at_recommendation: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    data_quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    run: Mapped["ResearchRun"] = relationship("ResearchRun")


class PersonalizedRecommendation(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "personalized_recommendations"
    __table_args__ = (
        Index("ix_personal_rec_symbol", "symbol"),
        Index("ix_personal_rec_action", "personal_action"),
    )

    neutral_recommendation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("neutral_recommendations.id", ondelete="CASCADE"),
        nullable=False,
    )
    investor_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("investor_profiles.id", ondelete="SET NULL"),
        nullable=True,
    )
    # portfolio_snapshot_id — no FK yet; portfolio_snapshots table added in M9
    portfolio_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    personal_action: Mapped[str] = mapped_column(String(30), nullable=False)
    position_sizing_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    policy_checks_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    current_position_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_allowed_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    personal_reason: Mapped[str] = mapped_column(Text, nullable=False)

    neutral: Mapped["NeutralRecommendation"] = relationship("NeutralRecommendation")
    investor_profile: Mapped["InvestorProfile | None"] = relationship("InvestorProfile")


class RecommendationEvidence(Base, UUIDMixin):
    """Evidence for a recommendation.

    recommendation_id has NO FK constraint intentionally: it may reference
    either neutral_recommendations.id or personalized_recommendations.id.
    Use recommendation_type to determine which table to look in.
    """

    __tablename__ = "recommendation_evidence"
    __table_args__ = (
        Index("ix_evidence_rec_id", "recommendation_id"),
        Index("ix_evidence_rec_type", "recommendation_type"),
    )

    recommendation_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    recommendation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source: Mapped[str | None] = mapped_column(String(200), nullable=True)
    source_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(PGTIMESTAMP(timezone=True), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        PGTIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class JobEvent(Base, UUIDMixin):
    __tablename__ = "job_events"
    __table_args__ = (
        Index("ix_job_events_entity", "entity_type", "entity_id"),
        Index("ix_job_events_event_type", "event_type"),
        Index("ix_job_events_correlation_id", "correlation_id"),
        Index("ix_job_events_created_at", "created_at"),
    )

    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        PGTIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class AuditLog(Base, UUIDMixin):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
        Index("ix_audit_logs_event_type", "event_type"),
        Index("ix_audit_logs_actor", "actor"),
        Index("ix_audit_logs_correlation_id", "correlation_id"),
        Index("ix_audit_logs_created_at", "created_at"),
    )

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="system")
    payload_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    correlation_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        PGTIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )


class MemoryIndexEvent(Base, UUIDMixin):
    """Audit trail for ChromaDB indexing. Rows with status=FAILED can be replayed."""

    __tablename__ = "memory_index_events"
    __table_args__ = (
        Index("ix_memory_index_events_entity", "entity_type", "entity_id"),
        Index("ix_memory_index_events_symbol", "symbol"),
        Index("ix_memory_index_events_status", "status"),
        Index("ix_memory_index_events_created_at", "created_at"),
    )

    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(20), nullable=True)
    collection_name: Mapped[str] = mapped_column(String(100), nullable=False)
    chroma_document_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # INDEXED | FAILED
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        PGTIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
