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
    "SocialPost",
    "BrokerAccount",
    "PortfolioAccount",
    "PortfolioPosition",
    "PortfolioSnapshot",
    "IBKRExecution",
    "ManualTrade",
    "TradingProfileSnapshot",
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
    "RecommendationOutcome",
    "LearningEvent",
    "AdvisorBacktestRun",
    "AdvisorBacktestTrade",
    "AdvisorBacktestEquityPoint",
    "AdvisorBacktestAnalysis",
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
            "symbol",
            "provider",
            "provider_article_id",
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


class SocialPost(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "social_posts"
    __table_args__ = (
        UniqueConstraint(
            "symbol",
            "provider",
            "provider_post_id",
            name="uq_social_symbol_provider_post",
        ),
        Index("ix_social_posts_symbol", "symbol"),
        Index("ix_social_posts_posted_at", "posted_at"),
        Index("ix_social_posts_provider", "provider"),
    )

    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_post_id: Mapped[str] = mapped_column(String(200), nullable=False)
    author_handle: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at: Mapped[datetime] = mapped_column(PGTIMESTAMP(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(PGTIMESTAMP(timezone=True), nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    sentiment_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    likes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reposts_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    replies_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class PortfolioAccount(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "portfolio_accounts"
    __table_args__ = (Index("ix_portfolio_accounts_user_id", "user_id"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_type: Mapped[str] = mapped_column(String(50), nullable=False, default="MANUAL")
    base_currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    cash_balance: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class PortfolioPosition(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "portfolio_positions"
    __table_args__ = (
        UniqueConstraint("account_id", "symbol", name="uq_position_account_symbol"),
        Index("ix_portfolio_positions_account_id", "account_id"),
        Index("ix_portfolio_positions_symbol", "symbol"),
        Index("ix_portfolio_positions_account_weight", "account_id", "weight"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("portfolio_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False)
    average_cost: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    current_price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    market_value: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    cost_basis: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    unrealized_pnl: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    unrealized_pnl_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    as_of_time: Mapped[datetime] = mapped_column(PGTIMESTAMP(timezone=True), nullable=False)

    account: Mapped["PortfolioAccount"] = relationship("PortfolioAccount")


class PortfolioSnapshot(Base, UUIDMixin):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        Index("ix_portfolio_snapshots_account_id", "account_id"),
        Index("ix_portfolio_snapshots_as_of_time", "as_of_time"),
        Index("ix_portfolio_snapshots_account_time", "account_id", "as_of_time"),
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("portfolio_accounts.id", ondelete="CASCADE"),
        nullable=False,
    )
    total_market_value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    cash_balance: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False, default=0)
    total_equity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    number_of_positions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_position_weight: Mapped[float | None] = mapped_column(Float, nullable=True)
    top_positions_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    sector_exposure_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    risk_metrics_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    as_of_time: Mapped[datetime] = mapped_column(PGTIMESTAMP(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        PGTIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )

    account: Mapped["PortfolioAccount"] = relationship("PortfolioAccount")


class BrokerAccount(Base, UUIDMixin, TimestampMixin):
    """One broker connection config per user/account.

    Supports LOCAL_TWS (host TWS/IB Gateway) and HOSTED_GATEWAY (container per user).
    Secrets are never stored here — only references to secret manager entries.
    """

    __tablename__ = "broker_accounts"
    __table_args__ = (
        Index("ix_broker_accounts_user_id", "user_id"),
        Index("ix_broker_accounts_provider", "provider"),
        Index("ix_broker_accounts_active", "is_active"),
    )

    # nullable until auth (M10+) enforces non-null
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, default="IBKR")
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_account_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    connection_mode: Mapped[str] = mapped_column(String(50), nullable=False, default="LOCAL_TWS")
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_id: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    readonly: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_sync_at: Mapped[datetime | None] = mapped_column(PGTIMESTAMP(timezone=True), nullable=True)
    last_sync_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    last_sync_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class IBKRExecution(Base, UUIDMixin, TimestampMixin):
    """IBKR execution row (session + Flex import).

    TODO (legacy transition): ``broker_account_id`` remains nullable. Postgres treats
    each NULL as distinct in ``UNIQUE(broker_account_id, exec_id)``, so unscoped rows
    are not deduped by that constraint. Future hardening: backfill or retire NULL
    broker rows, then set ``broker_account_id`` NOT NULL.
    """

    __tablename__ = "ibkr_executions"
    __table_args__ = (
        UniqueConstraint(
            "broker_account_id",
            "exec_id",
            name="uq_ibkr_executions_broker_exec_id",
        ),
        Index("ix_ibkr_executions_symbol", "symbol"),
        Index("ix_ibkr_executions_executed_at", "executed_at"),
        Index("ix_ibkr_executions_symbol_date", "symbol", "executed_at"),
        Index("ix_ibkr_executions_account", "account_id_ibkr"),
        Index("ix_ibkr_executions_side", "side"),
        Index("ix_ibkr_executions_broker_account_id", "broker_account_id"),
    )

    broker_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    account_id_ibkr: Mapped[str] = mapped_column(String(50), nullable=False)
    exec_id: Mapped[str] = mapped_column(String(255), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(50), nullable=True)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    commission: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="USD")
    executed_at: Mapped[datetime] = mapped_column(PGTIMESTAMP(timezone=True), nullable=False)
    order_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    broker_account: Mapped["BrokerAccount | None"] = relationship("BrokerAccount")


class ManualTrade(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "manual_trades"
    __table_args__ = (
        Index("ix_manual_trades_symbol", "symbol"),
        Index("ix_manual_trades_executed_at", "executed_at"),
        Index("ix_manual_trades_symbol_date", "symbol", "executed_at"),
        Index("ix_manual_trades_broker_account_id", "broker_account_id"),
    )

    broker_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    price: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(PGTIMESTAMP(timezone=True), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="manual")


class TradingProfileSnapshot(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "trading_profile_snapshots"
    __table_args__ = (
        Index("ix_trading_profile_as_of_date", "as_of_date"),
        Index("ix_trading_profile_period", "period_months"),
        Index("ix_trading_profile_broker_account_id", "broker_account_id"),
    )

    broker_account_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("broker_accounts.id", ondelete="SET NULL"),
        nullable=True,
    )

    period_months: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    as_of_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    total_executions: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_symbols_traded: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    win_rate: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    avg_winner_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    avg_loser_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    avg_holding_days: Mapped[float | None] = mapped_column(Numeric(8, 2), nullable=True)
    disposition_effect_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    concentration_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    recency_bias_score: Mapped[float | None] = mapped_column(Numeric(5, 4), nullable=True)
    behavioral_flags_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    per_symbol_stats_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    sector_stats_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    raw_metrics_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


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
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_watchlist_user_symbol"),
        Index("ix_watchlist_symbols_user_id", "user_id"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    company_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(20), nullable=True)
    asset_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default=AssetType.EQUITY.value
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class InvestorProfile(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "investor_profiles"
    __table_args__ = (Index("ix_investor_profiles_user_id", "user_id"),)

    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
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
        Index("ix_research_runs_user_id", "user_id"),
        Index("ix_research_runs_status", "status"),
        Index("ix_research_runs_run_type", "run_type"),
        Index("ix_research_runs_created_at", "created_at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
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
    symbol_trading_stats_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

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


# ── M11: Backtesting + Learning Loop ─────────────────────────────────────────


class RecommendationOutcome(Base, UUIDMixin, TimestampMixin):
    """Forward outcome measured for a neutral or personalized recommendation."""

    __tablename__ = "recommendation_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_type",
            "recommendation_id",
            "horizon_days",
            "benchmark_symbol",
            name="uq_outcome_rec_horizon_benchmark",
        ),
        Index("ix_outcome_user_id", "user_id"),
        Index("ix_outcome_symbol", "symbol"),
        Index("ix_outcome_research_run_id", "research_run_id"),
        Index("ix_outcome_rec_type_id", "recommendation_type", "recommendation_id"),
        Index("ix_outcome_measured_to", "measured_to"),
        Index("ix_outcome_status", "outcome_status"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    recommendation_type: Mapped[str] = mapped_column(String(30), nullable=False)
    recommendation_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    research_run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_at_recommendation: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    measured_from: Mapped[datetime] = mapped_column(PGTIMESTAMP(timezone=True), nullable=False)
    measured_to: Mapped[datetime] = mapped_column(PGTIMESTAMP(timezone=True), nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    benchmark_symbol: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="SPY", server_default=text("'SPY'")
    )
    start_price: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    end_price: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    benchmark_start_price: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    benchmark_end_price: Mapped[float | None] = mapped_column(Numeric(15, 4), nullable=True)
    forward_return_pct: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    benchmark_return_pct: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    relative_return_pct: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    max_runup_pct: Mapped[float | None] = mapped_column(Numeric(10, 6), nullable=True)
    # PENDING | MEASURED | INSUFFICIENT_DATA | ERROR
    outcome_status: Mapped[str] = mapped_column(String(30), nullable=False)
    # WIN | LOSS | NEUTRAL | AVOIDED_LOSS | MISSED_UPSIDE | UNKNOWN
    outcome_label: Mapped[str | None] = mapped_column(String(30), nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )


class LearningEvent(Base, UUIDMixin, TimestampMixin):
    """Rule-generated lesson from a bad call, missed upside, or scoring/data failure."""

    __tablename__ = "learning_events"
    __table_args__ = (
        Index("ix_learning_user_id", "user_id"),
        Index("ix_learning_symbol", "symbol"),
        Index("ix_learning_event_type", "event_type"),
        Index("ix_learning_status", "status"),
        Index("ix_learning_research_run_id", "research_run_id"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    recommendation_outcome_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("recommendation_outcomes.id", ondelete="SET NULL"),
        nullable=True,
    )
    research_run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    # UNDERPERFORMED_AFTER_BUY | MISSED_UPSIDE_AFTER_HOLD | AVOIDED_LOSS_AFTER_REDUCE
    # STOP_LOSS_LIKE_DRAWDOWN | DATA_QUALITY_ISSUE | THESIS_BROKEN
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    # LOW | MEDIUM | HIGH
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    suspected_causes_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    evidence_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    suggested_adjustments_json: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # OPEN | REVIEWED | DISMISSED | APPLIED
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="OPEN")

    outcome: Mapped["RecommendationOutcome | None"] = relationship("RecommendationOutcome")


# ── M11.1: Advisor Backtest (Follow-the-Advisor Simulation) ──────────────────


class AdvisorBacktestRun(Base, UUIDMixin, TimestampMixin):
    """One simulated paper-portfolio run following the advisor's recommendations."""

    __tablename__ = "advisor_backtest_runs"
    __table_args__ = (
        Index("ix_ab_run_user_id", "user_id"),
        Index("ix_ab_run_dates", "start_date", "end_date"),
        Index("ix_ab_run_status", "status"),
        Index("ix_ab_run_created_at", "created_at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    start_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    end_date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    initial_cash: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    final_equity: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    cash_final: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    total_return_pct: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_symbol: Mapped[str | None] = mapped_column(
        String(20), nullable=True, default="SPY", server_default=text("'SPY'")
    )
    benchmark_return_pct: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    relative_return_pct: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    total_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    winning_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    losing_trades: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # COMPLETED | INSUFFICIENT_DATA | ERROR
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    assumptions_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    summary_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    trades: Mapped[list["AdvisorBacktestTrade"]] = relationship(
        "AdvisorBacktestTrade", back_populates="run", cascade="all, delete-orphan"
    )
    equity_points: Mapped[list["AdvisorBacktestEquityPoint"]] = relationship(
        "AdvisorBacktestEquityPoint", back_populates="run", cascade="all, delete-orphan"
    )
    analyses: Mapped[list["AdvisorBacktestAnalysis"]] = relationship(
        "AdvisorBacktestAnalysis", back_populates="run", cascade="all, delete-orphan"
    )


class AdvisorBacktestTrade(Base, UUIDMixin, TimestampMixin):
    """One simulated trade or skip record within an advisor backtest run."""

    __tablename__ = "advisor_backtest_trades"
    __table_args__ = (
        Index("ix_ab_trade_run_id", "backtest_run_id"),
        Index("ix_ab_trade_user_id", "user_id"),
        Index("ix_ab_trade_symbol", "symbol"),
        Index("ix_ab_trade_date", "trade_date"),
    )

    backtest_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("advisor_backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    recommendation_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    research_run_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    action: Mapped[str] = mapped_column(String(30), nullable=False)
    # BUY | SELL | REDUCE | SKIP
    trade_type: Mapped[str] = mapped_column(String(20), nullable=False)
    trade_date: Mapped[datetime] = mapped_column(PGTIMESTAMP(timezone=True), nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    cash_delta: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    position_before: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    position_after: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    run: Mapped["AdvisorBacktestRun"] = relationship("AdvisorBacktestRun", back_populates="trades")


class AdvisorBacktestEquityPoint(Base, UUIDMixin, TimestampMixin):
    """Daily equity snapshot within an advisor backtest run."""

    __tablename__ = "advisor_backtest_equity_points"
    __table_args__ = (
        UniqueConstraint("backtest_run_id", "date", name="uq_ab_equity_run_date"),
        Index("ix_ab_equity_run_id", "backtest_run_id"),
        Index("ix_ab_equity_date", "date"),
    )

    backtest_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("advisor_backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    equity: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    cash: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    positions_value: Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)
    drawdown_pct: Mapped[float | None] = mapped_column(Numeric(18, 8), nullable=True)
    benchmark_value: Mapped[float | None] = mapped_column(Numeric(18, 4), nullable=True)
    raw_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    run: Mapped["AdvisorBacktestRun"] = relationship(
        "AdvisorBacktestRun", back_populates="equity_points"
    )


# ── M11.3: Advisor Backtest Analysis (local Ollama) ───────────────────────────


class AdvisorBacktestAnalysis(Base, UUIDMixin, TimestampMixin):
    """Ollama-generated analysis of one advisor backtest run."""

    __tablename__ = "advisor_backtest_analyses"
    __table_args__ = (
        Index("ix_aba_user_id", "user_id"),
        Index("ix_aba_run_id", "advisor_backtest_run_id"),
        Index("ix_aba_status", "status"),
        Index("ix_aba_created_at", "created_at"),
    )

    user_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    advisor_backtest_run_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("advisor_backtest_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, default="ollama", server_default=text("'ollama'")
    )
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="ollama_backtest_analyst_v1",
        server_default=text("'ollama_backtest_analyst_v1'"),
    )
    # COMPLETED | FAILED
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    analysis_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    prompt_input_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped["AdvisorBacktestRun"] = relationship(
        "AdvisorBacktestRun", back_populates="analyses"
    )
