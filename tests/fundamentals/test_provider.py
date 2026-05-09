"""Tests for yfinance fundamentals provider — mocks yfinance.Ticker.info."""

import datetime as dt
from unittest.mock import MagicMock, patch

import pytest
from core.errors import FundamentalsDataError
from fundamentals.yfinance_provider import YFinanceFundamentalsProvider


def _fake_info() -> dict:
    return {
        "quoteType": "EQUITY",
        "symbol": "AAPL",
        "trailingPE": 28.5,
        "forwardPE": 24.1,
        "priceToBook": 8.2,
        "priceToSalesTrailing12Months": 7.1,
        "revenueGrowth": 0.15,
        "earningsGrowth": 0.20,
        "profitMargins": 0.255,
        "grossMargins": 0.455,
        "operatingMargins": 0.302,
        "returnOnEquity": 0.451,
        "debtToEquity": 121.5,
        "currentRatio": 1.82,
        "freeCashflow": 95_000_000_000.0,
        "totalCash": 67_000_000_000.0,
        "totalDebt": 110_000_000_000.0,
        "marketCap": 2_800_000_000_000.0,
    }


def test_provider_name() -> None:
    assert YFinanceFundamentalsProvider().provider_name == "yfinance"


def test_fetch_returns_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = _fake_info()

    with patch("fundamentals.yfinance_provider.yf.Ticker", return_value=mock_ticker):
        provider = YFinanceFundamentalsProvider()
        snapshot = provider.fetch_company_fundamentals("AAPL")

    assert snapshot.symbol == "AAPL"
    assert snapshot.provider == "yfinance"
    assert snapshot.trailing_pe == pytest.approx(28.5, rel=1e-3)
    assert snapshot.revenue_growth == pytest.approx(0.15, rel=1e-3)
    assert snapshot.as_of_date == dt.date.today()
    # yfinance returns 121.5 (percentage), provider normalizes to ratio 1.215
    assert snapshot.debt_to_equity == pytest.approx(121.5 / 100.0, rel=1e-3)


def _make_ticker(dte_raw: float) -> MagicMock:
    t = MagicMock()
    t.info = {"quoteType": "EQUITY", "debtToEquity": dte_raw}
    return t


def test_dte_large_percentage_normalized() -> None:
    # 79.548% → 0.79548x ratio
    with patch("fundamentals.yfinance_provider.yf.Ticker", return_value=_make_ticker(79.548)):
        snap = YFinanceFundamentalsProvider().fetch_company_fundamentals("AAPL")
    assert snap.debt_to_equity == pytest.approx(0.79548, rel=1e-4)


def test_dte_small_percentage_normalized() -> None:
    # 7.25% → 0.0725x ratio (not 7.25x — yfinance always uses percentage form)
    with patch("fundamentals.yfinance_provider.yf.Ticker", return_value=_make_ticker(7.25)):
        snap = YFinanceFundamentalsProvider().fetch_company_fundamentals("AAPL")
    assert snap.debt_to_equity == pytest.approx(0.0725, rel=1e-4)


def test_dte_sub_one_percentage_normalized() -> None:
    # 0.8% → 0.008x ratio
    with patch("fundamentals.yfinance_provider.yf.Ticker", return_value=_make_ticker(0.8)):
        snap = YFinanceFundamentalsProvider().fetch_company_fundamentals("AAPL")
    assert snap.debt_to_equity == pytest.approx(0.008, rel=1e-4)


def test_dte_raw_preserved_in_raw_json() -> None:
    # raw_json keeps the original yfinance value for audit
    with patch("fundamentals.yfinance_provider.yf.Ticker", return_value=_make_ticker(79.548)):
        snap = YFinanceFundamentalsProvider().fetch_company_fundamentals("AAPL")
    assert snap.raw_json.get("debtToEquity") == pytest.approx(79.548, rel=1e-4)


def test_fetch_normalizes_symbol_to_uppercase() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = _fake_info()

    with patch("fundamentals.yfinance_provider.yf.Ticker", return_value=mock_ticker) as mock_cls:
        YFinanceFundamentalsProvider().fetch_company_fundamentals("aapl")
        mock_cls.assert_called_once_with("AAPL")


def test_fetch_empty_info_returns_stub() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = {}

    with patch("fundamentals.yfinance_provider.yf.Ticker", return_value=mock_ticker):
        snapshot = YFinanceFundamentalsProvider().fetch_company_fundamentals("ZZZZ")

    assert snapshot.symbol == "ZZZZ"
    assert snapshot.trailing_pe is None
    assert snapshot.completeness_score == pytest.approx(0.0)


def test_fetch_provider_failure_raises_error() -> None:
    with (
        patch("fundamentals.yfinance_provider.yf.Ticker", side_effect=RuntimeError("timeout")),
        pytest.raises(FundamentalsDataError),
    ):
        YFinanceFundamentalsProvider().fetch_company_fundamentals("AAPL")


def test_fetch_missing_fields_handled_gracefully() -> None:
    partial_info = {"quoteType": "EQUITY", "trailingPE": 22.0}
    mock_ticker = MagicMock()
    mock_ticker.info = partial_info

    with patch("fundamentals.yfinance_provider.yf.Ticker", return_value=mock_ticker):
        snapshot = YFinanceFundamentalsProvider().fetch_company_fundamentals("AAPL")

    assert snapshot.trailing_pe == pytest.approx(22.0)
    assert snapshot.revenue_growth is None
    assert snapshot.profit_margins is None


def test_completeness_score_reflects_available_fields() -> None:
    mock_ticker = MagicMock()
    mock_ticker.info = _fake_info()

    with patch("fundamentals.yfinance_provider.yf.Ticker", return_value=mock_ticker):
        snapshot = YFinanceFundamentalsProvider().fetch_company_fundamentals("AAPL")

    assert snapshot.completeness_score > 0.8
