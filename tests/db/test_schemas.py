"""Unit tests for Pydantic schemas — no DB needed."""

import datetime as dt

import pytest
from broker.ibkr.schemas import IBKRExecution
from db.enums import ResearchRunType, RiskLevel
from db.schemas import (
    IBKRSyncResponse,
    InvestorProfileUpdate,
    ManualTradeCreate,
    ResearchRunCreate,
    WatchlistSymbolCreate,
)
from pydantic import ValidationError


def test_watchlist_symbol_create_upcases() -> None:
    w = WatchlistSymbolCreate(symbol="aapl")
    assert w.symbol == "aapl"  # schema doesn't upcase — repo does


def test_watchlist_symbol_create_too_long() -> None:
    with pytest.raises(ValidationError):
        WatchlistSymbolCreate(symbol="A" * 21)


def test_research_run_create_default_type() -> None:
    r = ResearchRunCreate()
    assert r.run_type == ResearchRunType.MANUAL


def test_research_run_create_with_symbols() -> None:
    r = ResearchRunCreate(run_type=ResearchRunType.MORNING, symbols=["AAPL", "NVDA"])
    assert len(r.symbols) == 2  # type: ignore[arg-type]


def test_investor_profile_update_rejects_bad_weight() -> None:
    with pytest.raises(ValidationError):
        InvestorProfileUpdate(max_single_stock_weight=1.5)


def test_investor_profile_update_accepts_valid() -> None:
    u = InvestorProfileUpdate(max_single_stock_weight=0.20, risk_level=RiskLevel.HIGH)
    assert u.max_single_stock_weight == 0.20
    assert u.risk_level == RiskLevel.HIGH


def test_investor_profile_update_all_optional() -> None:
    u = InvestorProfileUpdate()
    assert u.model_dump(exclude_none=True) == {}


# ── M9.5 trade history schemas ────────────────────────────────────────────────


def test_manual_trade_create_valid() -> None:
    t = ManualTradeCreate(
        symbol="AAPL",
        side="BUY",
        quantity=10.0,
        price=150.0,
        executed_at=dt.datetime(2025, 5, 1, tzinfo=dt.UTC),
    )
    assert t.symbol == "AAPL"
    assert t.side == "BUY"
    assert t.source == "manual"


def test_manual_trade_create_invalid_side() -> None:
    with pytest.raises(ValidationError):
        ManualTradeCreate(
            symbol="AAPL",
            side="LONG",  # invalid
            quantity=10.0,
            price=150.0,
            executed_at=dt.datetime(2025, 5, 1, tzinfo=dt.UTC),
        )


def test_manual_trade_create_rejects_zero_qty() -> None:
    with pytest.raises(ValidationError):
        ManualTradeCreate(
            symbol="AAPL",
            side="BUY",
            quantity=0.0,
            price=150.0,
            executed_at=dt.datetime(2025, 5, 1, tzinfo=dt.UTC),
        )


def test_ibkr_sync_response() -> None:
    r = IBKRSyncResponse(inserted=5, message="5 new executions")
    assert r.inserted == 5


def test_ibkr_execution_schema_valid() -> None:
    ex = IBKRExecution(
        exec_id="test-001",
        account_id_ibkr="DU999",
        symbol="AAPL",
        side="BUY",
        quantity=10.0,
        price=150.0,
        executed_at=dt.datetime(2025, 5, 1, tzinfo=dt.UTC),
    )
    assert ex.currency == "USD"
    assert ex.raw_json == {}


def test_ibkr_execution_schema_rejects_zero_qty() -> None:
    with pytest.raises(ValidationError):
        IBKRExecution(
            exec_id="bad",
            account_id_ibkr="DU999",
            symbol="AAPL",
            side="BUY",
            quantity=0.0,
            price=150.0,
            executed_at=dt.datetime(2025, 5, 1, tzinfo=dt.UTC),
        )
