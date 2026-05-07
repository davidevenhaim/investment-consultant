"""FetchMarketData — mock OHLCV data. Real yfinance in M4."""
from typing import Any

import pandas as pd
from core.logging import get_logger

from research_graph.state import ResearchState

logger = get_logger(__name__)

# Mock base prices per symbol — deterministic, realistic
_BASE_PRICES: dict[str, float] = {
    "AAPL": 190.25,
    "NVDA": 845.00,
    "TSLA": 232.00,
    "SPY": 510.00,
    "QQQ": 430.00,
    "MSFT": 415.00,
    "AMZN": 185.00,
    "GOOGL": 175.00,
    "META": 520.00,
}
_DEFAULT_PRICE = 100.00


def _mock_ohlcv(symbol: str) -> pd.DataFrame:
    """Return 30 rows of deterministic fake OHLCV. No randomness — same output per symbol."""
    base = _BASE_PRICES.get(symbol.upper(), _DEFAULT_PRICE)
    seed = sum(ord(c) * (i + 1) for i, c in enumerate(symbol))
    n = 30

    closes: list[float] = [base]
    for i in range(n - 1):
        # Deterministic walk: +/- 0.3% to 1.5% per day
        step_pct = ((seed * (i + 7)) % 19 - 9) * 0.0017
        closes.append(round(closes[-1] * (1 + step_pct), 4))

    def vary(price: float, up_pct: float, down_pct: float) -> float:
        return round(price * (1 + up_pct), 4)

    data = {
        "open": [vary(c, 0.002, 0.002) for c in closes],
        "high": [vary(c, 0.012, 0.0) for c in closes],
        "low": [vary(c, -0.012, 0.0) for c in closes],
        "close": closes,
        "volume": [1_000_000 + (seed * (i + 3)) % 900_000 for i in range(n)],
    }
    idx = pd.date_range(end=pd.Timestamp.utcnow().normalize(), periods=n, freq="B")
    return pd.DataFrame(data, index=idx)


def fetch_market_data(state: ResearchState) -> dict[str, Any]:
    """
    Return mock OHLCV DataFrame for the symbol.
    Real yfinance 5-year history implemented in M4.
    """
    symbol = state["symbol"]
    try:
        ohlcv = _mock_ohlcv(symbol)
        logger.info("node_fetch_market_data", symbol=symbol, rows=len(ohlcv), source="mock")
        return {"ohlcv": ohlcv, "data_quality_score": 0.9}
    except Exception as exc:
        logger.warning("node_fetch_market_data_failed", symbol=symbol, error=str(exc))
        return {
            "ohlcv": None,
            "errors": [f"fetch_market_data_failed: {exc}"],
            "confidence_penalties": [0.20],
        }
