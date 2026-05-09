"""Shared fixtures for fundamentals tests."""
import datetime as dt

import pytest
from fundamentals.interfaces import FundamentalsProvider
from fundamentals.schemas import CompanyFundamentalsSnapshot


def _make_snapshot(
    symbol: str = "AAPL",
    trailing_pe: float | None = 28.0,
    forward_pe: float | None = 24.0,
    revenue_growth: float | None = 0.15,
    earnings_growth: float | None = 0.20,
    profit_margins: float | None = 0.25,
    gross_margins: float | None = 0.45,
    operating_margins: float | None = 0.30,
    return_on_equity: float | None = 0.45,
    debt_to_equity: float | None = 1.20,
    current_ratio: float | None = 1.80,
    price_to_book: float | None = 8.0,
    price_to_sales: float | None = 7.0,
    market_cap: float | None = 2_800_000_000_000.0,
    enterprise_to_revenue: float | None = None,
    enterprise_to_ebitda: float | None = None,
    free_cashflow: float | None = 95_000_000_000.0,
    total_cash: float | None = None,
    total_debt: float | None = None,
    provider: str = "mock",
) -> CompanyFundamentalsSnapshot:
    return CompanyFundamentalsSnapshot(
        symbol=symbol,
        as_of_date=dt.date(2026, 1, 15),
        provider=provider,
        trailing_pe=trailing_pe,
        forward_pe=forward_pe,
        revenue_growth=revenue_growth,
        earnings_growth=earnings_growth,
        profit_margins=profit_margins,
        gross_margins=gross_margins,
        operating_margins=operating_margins,
        return_on_equity=return_on_equity,
        debt_to_equity=debt_to_equity,
        current_ratio=current_ratio,
        price_to_book=price_to_book,
        price_to_sales=price_to_sales,
        enterprise_to_revenue=enterprise_to_revenue,
        enterprise_to_ebitda=enterprise_to_ebitda,
        market_cap=market_cap,
        free_cashflow=free_cashflow,
        total_cash=total_cash,
        total_debt=total_debt,
    )


_MOCK_FUNDAMENTALS: dict[str, dict] = {
    "AAPL": {
        "trailing_pe": 28.0, "forward_pe": 24.0,
        "revenue_growth": 0.15, "earnings_growth": 0.20,
        "profit_margins": 0.25, "gross_margins": 0.45,
        "operating_margins": 0.30, "return_on_equity": 0.45,
        "debt_to_equity": 1.20, "current_ratio": 1.80,
        "price_to_book": 8.0, "price_to_sales": 7.0,
    },
    "NVDA": {
        "trailing_pe": 55.0, "forward_pe": 35.0,
        "revenue_growth": 0.85, "earnings_growth": 1.20,
        "profit_margins": 0.55, "gross_margins": 0.73,
        "operating_margins": 0.58, "return_on_equity": 1.20,
        "debt_to_equity": 0.50, "current_ratio": 4.20,
        "price_to_book": 25.0, "price_to_sales": 28.0,
    },
    "TSLA": {
        "trailing_pe": 45.0, "forward_pe": 50.0,
        "revenue_growth": 0.02, "earnings_growth": -0.30,
        "profit_margins": 0.08, "gross_margins": 0.18,
        "operating_margins": 0.06, "return_on_equity": 0.10,
        "debt_to_equity": 0.50, "current_ratio": 1.90,
        "price_to_book": 7.0, "price_to_sales": 6.0,
    },
    "MSFT": {
        "trailing_pe": 35.0, "forward_pe": 28.0,
        "revenue_growth": 0.18, "earnings_growth": 0.22,
        "profit_margins": 0.36, "gross_margins": 0.70,
        "operating_margins": 0.45, "return_on_equity": 0.38,
        "debt_to_equity": 0.40, "current_ratio": 1.80,
        "price_to_book": 12.0, "price_to_sales": 12.0,
    },
}


class MockFundamentalsProvider(FundamentalsProvider):
    """Deterministic fundamentals for known symbols; empty for unknown."""

    @property
    def provider_name(self) -> str:
        return "mock"

    def fetch_company_fundamentals(self, symbol: str) -> CompanyFundamentalsSnapshot:
        data = _MOCK_FUNDAMENTALS.get(symbol.upper(), {})
        return _make_snapshot(symbol=symbol.upper(), provider="mock", **data)  # type: ignore[arg-type]


@pytest.fixture
def mock_fundamentals_provider() -> MockFundamentalsProvider:
    return MockFundamentalsProvider()


@pytest.fixture
def good_snapshot() -> CompanyFundamentalsSnapshot:
    return _make_snapshot("AAPL")


@pytest.fixture
def weak_snapshot() -> CompanyFundamentalsSnapshot:
    return _make_snapshot(
        "TSLA",
        trailing_pe=45.0, forward_pe=50.0,
        revenue_growth=0.02, earnings_growth=-0.30,
        profit_margins=0.08, return_on_equity=0.10,
        debt_to_equity=0.50,
    )


@pytest.fixture
def empty_snapshot() -> CompanyFundamentalsSnapshot:
    return CompanyFundamentalsSnapshot(
        symbol="ZZZZ",
        as_of_date=dt.date(2026, 1, 15),
        provider="mock",
    )
