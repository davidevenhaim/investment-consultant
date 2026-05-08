"""Shared fixtures for market_data tests."""
import datetime as dt

import pytest
from market_data.interfaces import MarketDataProvider
from market_data.schemas import MarketPriceBar


def _make_bars(
    symbol: str,
    n: int = 260,
    base: float = 100.0,
    step: float = 0.20,
    start: dt.date | None = None,
) -> list[MarketPriceBar]:
    if start is None:
        start = dt.date(2023, 1, 1)
    bars = []
    price = base
    current = start
    for i in range(n):
        # Skip weekends
        while current.weekday() >= 5:
            current += dt.timedelta(days=1)
        bars.append(
            MarketPriceBar(
                symbol=symbol,
                price_date=current,
                open=round(price * 0.999, 4),
                high=round(price * 1.01, 4),
                low=round(price * 0.99, 4),
                close=round(price + step * i, 4),
                adjusted_close=round(price + step * i, 4),
                volume=1_000_000,
                provider="mock",
            )
        )
        current += dt.timedelta(days=1)
    return bars


class MockProvider(MarketDataProvider):
    """Returns deterministic bars for known symbols; empty for unknown."""

    _SYMBOLS = {
        "AAPL": {"base": 170.0, "step": 0.15},
        "NVDA": {"base": 500.0, "step": 1.20},
        "TSLA": {"base": 200.0, "step": -0.10},
        "SPY": {"base": 400.0, "step": 0.20},
        "MSFT": {"base": 350.0, "step": 0.30},
    }

    @property
    def provider_name(self) -> str:
        return "mock"

    def fetch_historical_prices(
        self,
        symbol: str,
        start_date: dt.date,
        end_date: dt.date,
    ) -> list[MarketPriceBar]:
        cfg = self._SYMBOLS.get(symbol.upper())
        if cfg is None:
            return []
        return _make_bars(
            symbol.upper(),
            n=1300,
            base=cfg["base"],
            step=cfg["step"],
            start=dt.date(2020, 1, 2),
        )


@pytest.fixture
def mock_provider() -> MockProvider:
    return MockProvider()
