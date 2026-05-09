"""Unit tests for technical indicator calculations — no DB, no network."""

import pytest
from market_data.indicators import (
    atr_pct,
    compute_all_signals,
    max_drawdown,
    relative_strength,
    return_n_bars,
    rsi,
    sma,
    volatility_annualized,
)


def _linear(start: float, step: float, n: int) -> list[float]:
    return [start + i * step for i in range(n)]


# ── sma ───────────────────────────────────────────────────────────────────────


def test_sma_correct() -> None:
    assert sma([1.0, 2.0, 3.0, 4.0, 5.0], 3) == pytest.approx(4.0)


def test_sma_insufficient_data_returns_none() -> None:
    assert sma([1.0, 2.0], 5) is None


# ── return_n_bars ─────────────────────────────────────────────────────────────


def test_return_n_bars_positive() -> None:
    closes = _linear(100.0, 1.0, 30)  # 100→129
    r = return_n_bars(closes, 21)
    assert r is not None
    assert r > 0


def test_return_n_bars_negative() -> None:
    closes = _linear(130.0, -1.0, 30)  # 130→101
    r = return_n_bars(closes, 21)
    assert r is not None
    assert r < 0


def test_return_n_bars_insufficient() -> None:
    assert return_n_bars([100.0, 101.0], 5) is None


# ── volatility_annualized ─────────────────────────────────────────────────────


def test_volatility_flat_series_near_zero() -> None:
    closes = [100.0] * 50
    vol = volatility_annualized(closes, 30)
    assert vol == pytest.approx(0.0, abs=1e-9)


def test_volatility_positive_for_varying_series() -> None:
    import random

    random.seed(42)
    closes = [100.0 * (1 + random.gauss(0, 0.01)) for _ in range(60)]
    vol = volatility_annualized(closes, 30)
    assert vol is not None
    assert vol > 0


def test_volatility_insufficient_returns_none() -> None:
    assert volatility_annualized([100.0] * 10, 30) is None


# ── max_drawdown ──────────────────────────────────────────────────────────────


def test_max_drawdown_no_drawdown() -> None:
    closes = _linear(100.0, 1.0, 50)
    mdd = max_drawdown(closes, 50)
    assert mdd == pytest.approx(0.0, abs=1e-9)


def test_max_drawdown_known_value() -> None:
    closes = [100.0, 120.0, 80.0, 90.0]
    mdd = max_drawdown(closes, 4)
    # peak=120, trough=80 → dd = (80-120)/120 = -1/3
    assert mdd is not None
    assert mdd == pytest.approx(-1 / 3, rel=1e-4)


# ── rsi ───────────────────────────────────────────────────────────────────────


def test_rsi_all_gains_returns_100() -> None:
    closes = _linear(100.0, 1.0, 20)
    r = rsi(closes, 14)
    assert r == pytest.approx(100.0)


def test_rsi_all_losses_returns_zero() -> None:
    closes = _linear(120.0, -1.0, 20)
    r = rsi(closes, 14)
    assert r is not None
    assert r < 5.0


def test_rsi_neutral_series() -> None:
    # alternating up/down → RSI near 50
    closes = [100.0 + (1 if i % 2 == 0 else -1) for i in range(30)]
    r = rsi(closes, 14)
    assert r is not None
    assert 40.0 < r < 60.0


def test_rsi_insufficient_returns_none() -> None:
    assert rsi([100.0] * 5, 14) is None


# ── atr_pct ───────────────────────────────────────────────────────────────────


def test_atr_pct_stable_returns_small_value() -> None:
    n = 20
    closes = [100.0] * n
    highs = [101.0] * n
    lows = [99.0] * n
    val = atr_pct(highs, lows, closes, 14)
    assert val is not None
    assert val == pytest.approx(2.0 / 100.0, rel=0.1)


def test_atr_pct_insufficient_returns_none() -> None:
    assert atr_pct([101.0] * 5, [99.0] * 5, [100.0] * 5, 14) is None


# ── relative_strength ─────────────────────────────────────────────────────────


def test_relative_strength_outperforming() -> None:
    # symbol up 10%, bench up 5%
    sym = _linear(100.0, 10.0 / 63, 70)
    bench = _linear(100.0, 5.0 / 63, 70)
    rs = relative_strength(sym, bench, 63)
    assert rs is not None
    assert rs > 0


def test_relative_strength_underperforming() -> None:
    sym = _linear(100.0, -5.0 / 63, 70)
    bench = _linear(100.0, 5.0 / 63, 70)
    rs = relative_strength(sym, bench, 63)
    assert rs is not None
    assert rs < 0


def test_relative_strength_insufficient_bench() -> None:
    sym = _linear(100.0, 1.0, 70)
    bench = [100.0] * 10
    assert relative_strength(sym, bench, 63) is None


# ── compute_all_signals ───────────────────────────────────────────────────────


def test_compute_all_signals_returns_required_keys() -> None:
    closes = _linear(100.0, 0.5, 260)
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    spy = _linear(400.0, 0.2, 260)

    signals = compute_all_signals("AAPL", closes, highs, lows, spy)

    required = [
        "trading_days_count",
        "latest_close",
        "return_1m",
        "return_3m",
        "return_6m",
        "return_12m",
        "volatility_30d",
        "volatility_90d",
        "max_drawdown_1y",
        "sma_20",
        "sma_50",
        "sma_200",
        "price_vs_sma_20",
        "price_vs_sma_50",
        "price_vs_sma_200",
        "rsi_14",
        "atr_14_pct",
        "relative_strength_3m_vs_spy",
        "relative_strength_12m_vs_spy",
    ]
    for key in required:
        assert key in signals, f"missing key: {key}"


def test_compute_all_signals_no_spy_gives_none_rs() -> None:
    closes = _linear(100.0, 0.5, 260)
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]

    signals = compute_all_signals("AAPL", closes, highs, lows, None)
    assert signals["relative_strength_3m_vs_spy"] is None
    assert signals["relative_strength_12m_vs_spy"] is None


def test_compute_all_signals_insufficient_data_graceful() -> None:
    closes = [100.0] * 10
    highs = [101.0] * 10
    lows = [99.0] * 10
    signals = compute_all_signals("AAPL", closes, highs, lows, None)
    # Short series: many signals None, but function doesn't raise
    assert signals["trading_days_count"] == 10
    assert signals["sma_200"] is None
    assert signals["rsi_14"] is None
