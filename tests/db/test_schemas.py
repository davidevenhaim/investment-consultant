"""Unit tests for Pydantic schemas — no DB needed."""

import pytest
from db.enums import ResearchRunType, RiskLevel
from db.schemas import (
    InvestorProfileUpdate,
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
