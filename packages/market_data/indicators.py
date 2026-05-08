"""Pure-Python/numpy technical indicator calculations.

All functions take a list of floats (closes or OHLCV) ordered oldest→newest.
Returns None when insufficient data rather than raising.
"""
import math
from typing import Any


def _returns(closes: list[float], lookback: int) -> float | None:
    if len(closes) < lookback + 1:
        return None
    return (closes[-1] / closes[-lookback - 1]) - 1.0


def return_n_bars(closes: list[float], n: int) -> float | None:
    return _returns(closes, n)


def sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def price_vs_sma(closes: list[float], period: int) -> float | None:
    s = sma(closes, period)
    if s is None or s == 0:
        return None
    return closes[-1] / s


def volatility_annualized(closes: list[float], period: int) -> float | None:
    """Annualized daily-return std dev over last `period` bars."""
    if len(closes) < period + 1:
        return None
    rets = [(closes[i] / closes[i - 1]) - 1.0 for i in range(len(closes) - period, len(closes))]
    n = len(rets)
    mean = sum(rets) / n
    variance = sum((r - mean) ** 2 for r in rets) / (n - 1) if n > 1 else 0.0
    return math.sqrt(variance) * math.sqrt(252)


def max_drawdown(closes: list[float], lookback: int) -> float | None:
    """Maximum drawdown (negative fraction) over last `lookback` bars."""
    window = closes[-lookback:] if len(closes) >= lookback else closes
    if not window:
        return None
    peak = window[0]
    max_dd = 0.0
    for price in window:
        if price > peak:
            peak = price
        dd = (price - peak) / peak
        if dd < max_dd:
            max_dd = dd
    return max_dd


def rsi(closes: list[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(len(closes) - period, len(closes)):
        change = closes[i] - closes[i - 1]
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def atr_pct(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> float | None:
    """ATR as % of latest close."""
    if len(closes) < period + 1:
        return None
    trs = []
    for i in range(len(closes) - period, len(closes)):
        prev_close = closes[i - 1]
        tr = max(highs[i] - lows[i], abs(highs[i] - prev_close), abs(lows[i] - prev_close))
        trs.append(tr)
    atr_val = sum(trs) / period
    if closes[-1] == 0:
        return None
    return atr_val / closes[-1]


def relative_strength(
    symbol_closes: list[float],
    bench_closes: list[float],
    lookback: int,
) -> float | None:
    """(symbol_return - benchmark_return) over lookback bars."""
    sym_ret = _returns(symbol_closes, lookback)
    bench_ret = _returns(bench_closes, lookback)
    if sym_ret is None or bench_ret is None:
        return None
    return sym_ret - bench_ret


def compute_all_signals(
    symbol: str,
    closes: list[float],
    highs: list[float],
    lows: list[float],
    spy_closes: list[float] | None,
) -> dict[str, Any]:
    """Compute all required M4 technical signals from price series."""
    n = len(closes)
    signals: dict[str, Any] = {
        "symbol": symbol,
        "trading_days_count": n,
        "latest_close": closes[-1] if closes else None,
    }

    # Returns
    approx_trading = {1: 21, 3: 63, 6: 126, 12: 252}
    for months, bars in approx_trading.items():
        signals[f"return_{months}m"] = return_n_bars(closes, bars)

    # Volatility
    signals["volatility_30d"] = volatility_annualized(closes, 30)
    signals["volatility_90d"] = volatility_annualized(closes, 90)

    # Max drawdown 1 year
    signals["max_drawdown_1y"] = max_drawdown(closes, 252)

    # SMAs
    for period in (20, 50, 200):
        signals[f"sma_{period}"] = sma(closes, period)
        signals[f"price_vs_sma_{period}"] = price_vs_sma(closes, period)

    # RSI
    signals["rsi_14"] = rsi(closes)

    # ATR%
    signals["atr_14_pct"] = atr_pct(highs, lows, closes)

    # Relative strength
    signals["relative_strength_3m_vs_spy"] = (
        relative_strength(closes, spy_closes, 63) if spy_closes else None
    )
    signals["relative_strength_12m_vs_spy"] = (
        relative_strength(closes, spy_closes, 252) if spy_closes else None
    )

    return signals
