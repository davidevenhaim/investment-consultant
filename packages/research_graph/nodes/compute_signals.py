"""ComputeSignals — mock technical signals. Real pandas-ta indicators in M4."""
from typing import Any

import pandas as pd
from core.logging import get_logger

from research_graph.state import ResearchState

logger = get_logger(__name__)

# Pre-computed mock signals per symbol. Values are calibrated to produce a
# realistic spread of scores: NVDA > AAPL (BUY_CANDIDATE), TSLA (HOLD).
_MOCK_SIGNALS: dict[str, dict[str, float]] = {
    "AAPL": {
        "rsi": 58.0,
        "macd": 0.82,
        "macd_signal": 0.65,
        "macd_histogram": 0.17,
        "ema_20": 187.50,
        "ema_50": 182.30,
        "price": 190.25,
        "price_vs_ema20": 190.25 / 187.50,  # ~1.015
        "momentum_1m": 0.038,
        "atr": 3.20,
        "atr_pct": 0.017,
        "volume_ratio": 1.15,
    },
    "NVDA": {
        "rsi": 66.0,
        "macd": 4.50,
        "macd_signal": 3.20,
        "macd_histogram": 1.30,
        "ema_20": 820.0,
        "ema_50": 790.0,
        "price": 845.0,
        "price_vs_ema20": 845.0 / 820.0,  # ~1.030
        "momentum_1m": 0.072,
        "atr": 22.0,
        "atr_pct": 0.026,
        "volume_ratio": 1.35,
    },
    "TSLA": {
        "rsi": 41.0,
        "macd": -2.10,
        "macd_signal": -1.30,
        "macd_histogram": -0.80,
        "ema_20": 240.0,
        "ema_50": 252.0,
        "price": 232.0,
        "price_vs_ema20": 232.0 / 240.0,  # ~0.967
        "momentum_1m": -0.042,
        "atr": 9.50,
        "atr_pct": 0.041,
        "volume_ratio": 0.95,
    },
}

_DEFAULT_SIGNALS: dict[str, float] = {
    "rsi": 50.0,
    "macd": 0.0,
    "macd_signal": 0.0,
    "macd_histogram": 0.0,
    "ema_20": 100.0,
    "ema_50": 100.0,
    "price": 100.0,
    "price_vs_ema20": 1.0,
    "momentum_1m": 0.0,
    "atr": 2.0,
    "atr_pct": 0.02,
    "volume_ratio": 1.0,
}


def _derive_signals(ohlcv: Any, symbol: str) -> dict[str, float]:
    """Derive signal from OHLCV if available. Fall back to mock lookup."""
    signals = dict(_MOCK_SIGNALS.get(symbol.upper(), _DEFAULT_SIGNALS))

    if ohlcv is not None and isinstance(ohlcv, pd.DataFrame) and len(ohlcv) >= 5:
        closes = ohlcv["close"].tolist()
        signals["price"] = closes[-1]
        # momentum_1m computed from real data in M4; keep mock value for M3

    return signals


def compute_signals(state: ResearchState) -> dict[str, Any]:
    """
    Compute technical signals from OHLCV data.
    Returns mock per-symbol signals in M3; real pandas-ta indicators in M4.
    """
    symbol = state["symbol"]
    ohlcv = state.get("ohlcv")
    try:
        signals = _derive_signals(ohlcv, symbol)
        logger.info("node_compute_signals", symbol=symbol, rsi=signals.get("rsi"))
        return {"technical_signals": signals}
    except Exception as exc:
        logger.warning("node_compute_signals_failed", symbol=symbol, error=str(exc))
        return {
            "technical_signals": None,
            "errors": [f"compute_signals_failed: {exc}"],
            "confidence_penalties": [0.10],
        }
