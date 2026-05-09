"""Tests for yfinance provider — mocks yfinance.Ticker to avoid network."""

import datetime as dt
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from core.errors import MarketDataError
from market_data.yfinance_provider import YFinanceProvider


def _fake_df(n: int = 30) -> pd.DataFrame:
    import numpy as np

    dates = pd.date_range("2024-01-02", periods=n, freq="B")
    closes = 150.0 + np.arange(n, dtype=float)
    return pd.DataFrame(
        {
            "Open": closes - 0.5,
            "High": closes + 1.0,
            "Low": closes - 1.0,
            "Close": closes,
            "Adj Close": closes,
            "Volume": [1_000_000] * n,
        },
        index=dates,
    )


def test_provider_name() -> None:
    assert YFinanceProvider().provider_name == "yfinance"


def test_fetch_returns_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _fake_df(30)

    with patch("market_data.yfinance_provider.yf.Ticker", return_value=mock_ticker):
        provider = YFinanceProvider()
        bars = provider.fetch_historical_prices(
            "AAPL",
            dt.date(2024, 1, 2),
            dt.date(2024, 2, 15),
        )

    assert len(bars) == 30
    assert all(b.symbol == "AAPL" for b in bars)
    assert all(b.provider == "yfinance" for b in bars)
    assert bars == sorted(bars, key=lambda b: b.price_date)


def test_fetch_empty_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = pd.DataFrame()

    with patch("market_data.yfinance_provider.yf.Ticker", return_value=mock_ticker):
        provider = YFinanceProvider()
        bars = provider.fetch_historical_prices(
            "ZZZZ",
            dt.date(2024, 1, 2),
            dt.date(2024, 2, 15),
        )

    assert bars == []


def test_fetch_provider_exception_raises_market_data_error() -> None:
    with patch("market_data.yfinance_provider.yf.Ticker", side_effect=RuntimeError("timeout")):
        provider = YFinanceProvider()
        with pytest.raises(MarketDataError):
            provider.fetch_historical_prices(
                "AAPL",
                dt.date(2024, 1, 2),
                dt.date(2024, 2, 15),
            )


def test_fetch_normalizes_symbol_to_uppercase(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_ticker = MagicMock()
    mock_ticker.history.return_value = _fake_df(5)

    with patch("market_data.yfinance_provider.yf.Ticker", return_value=mock_ticker) as mock_cls:
        provider = YFinanceProvider()
        provider.fetch_historical_prices("aapl", dt.date(2024, 1, 2), dt.date(2024, 1, 10))
        mock_cls.assert_called_once_with("AAPL")
