"""Tests for deterministic trading profile engine."""

import datetime as dt

import pytest
from broker.ibkr.schemas import IBKRExecution
from portfolio.trading_profile import (
    TradePair,
    _concentration_score,
    _disposition_effect_score,
    _fifo_match,
    _win_rate,
    build_trading_profile,
)


def _exec(
    exec_id: str,
    symbol: str,
    side: str,
    qty: float,
    price: float,
    days_ago: int,
) -> IBKRExecution:
    ts = dt.datetime(2025, 1, 1, tzinfo=dt.UTC) + dt.timedelta(days=days_ago)
    return IBKRExecution(
        exec_id=exec_id,
        account_id_ibkr="DU999",
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        quantity=qty,
        price=price,
        executed_at=ts,
    )


class TestFifoMatch:
    def test_simple_pair(self) -> None:
        execs = [
            _exec("b1", "AAPL", "BUY", 10, 100, 0),
            _exec("s1", "AAPL", "SELL", 10, 120, 30),
        ]
        pairs, open_qty = _fifo_match(execs)
        assert len(pairs) == 1
        assert pairs[0].pnl_pct == pytest.approx(0.20)
        assert pairs[0].is_winner is True
        assert open_qty.get("AAPL", 0) == pytest.approx(0)

    def test_partial_sell(self) -> None:
        execs = [
            _exec("b1", "AAPL", "BUY", 10, 100, 0),
            _exec("s1", "AAPL", "SELL", 5, 120, 30),
        ]
        pairs, open_qty = _fifo_match(execs)
        assert len(pairs) == 1
        assert pairs[0].quantity == pytest.approx(5)
        assert open_qty.get("AAPL", 0) == pytest.approx(5)

    def test_loser_pair(self) -> None:
        execs = [
            _exec("b1", "NVDA", "BUY", 5, 400, 0),
            _exec("s1", "NVDA", "SELL", 5, 350, 30),
        ]
        pairs, _ = _fifo_match(execs)
        assert pairs[0].is_winner is False
        assert pairs[0].pnl_pct == pytest.approx(-0.125)

    def test_open_position_not_in_pairs(self) -> None:
        execs = [
            _exec("b1", "TSLA", "BUY", 8, 200, 0),
        ]
        pairs, open_qty = _fifo_match(execs)
        assert len(pairs) == 0
        assert open_qty["TSLA"] == pytest.approx(8)

    def test_multiple_symbols(self) -> None:
        execs = [
            _exec("b1", "AAPL", "BUY", 10, 100, 0),
            _exec("b2", "NVDA", "BUY", 5, 400, 5),
            _exec("s1", "AAPL", "SELL", 10, 130, 30),
            _exec("s2", "NVDA", "SELL", 5, 380, 60),
        ]
        pairs, open_qty = _fifo_match(execs)
        assert len(pairs) == 2
        assert sum(1 for p in pairs if p.is_winner) == 1  # AAPL wins, NVDA loses


class TestWinRate:
    def test_50_pct(self) -> None:
        pairs = [
            TradePair("A", 100, 120, 1, dt.datetime(2025, 1, 1, tzinfo=dt.UTC), dt.datetime(2025, 2, 1, tzinfo=dt.UTC)),
            TradePair("A", 100, 80, 1, dt.datetime(2025, 1, 1, tzinfo=dt.UTC), dt.datetime(2025, 2, 1, tzinfo=dt.UTC)),
        ]
        assert _win_rate(pairs) == pytest.approx(0.5)

    def test_empty(self) -> None:
        assert _win_rate([]) is None


class TestDispositionEffect:
    def test_positive_disposition(self) -> None:
        # Winners held 10 days, losers held 40 days → strong disposition effect
        winner = TradePair("A", 100, 120, 1,
                           dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
                           dt.datetime(2025, 1, 11, tzinfo=dt.UTC))
        loser = TradePair("A", 100, 80, 1,
                          dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
                          dt.datetime(2025, 2, 10, tzinfo=dt.UTC))
        score = _disposition_effect_score([winner, loser])
        assert score is not None
        assert score > 0.5  # (40-10)/40 = 0.75

    def test_no_disposition_if_symmetric(self) -> None:
        # Same holding time → score near 0
        winner = TradePair("A", 100, 120, 1,
                           dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
                           dt.datetime(2025, 1, 31, tzinfo=dt.UTC))
        loser = TradePair("A", 100, 80, 1,
                          dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
                          dt.datetime(2025, 1, 31, tzinfo=dt.UTC))
        score = _disposition_effect_score([winner, loser])
        assert score is not None
        assert score == pytest.approx(0.0, abs=0.01)


class TestConcentration:
    def test_single_symbol_max(self) -> None:
        execs = [
            _exec("b1", "AAPL", "BUY", 10, 100, 0),
            _exec("s1", "AAPL", "SELL", 5, 100, 30),
        ]
        score = _concentration_score(execs)
        assert score == pytest.approx(1.0)

    def test_two_equal_symbols(self) -> None:
        execs = [
            _exec("b1", "AAPL", "BUY", 10, 100, 0),
            _exec("b2", "NVDA", "BUY", 10, 100, 0),
        ]
        score = _concentration_score(execs)
        assert score == pytest.approx(0.5)


class TestBuildTradingProfile:
    def test_fake_executions(self) -> None:
        from broker.ibkr.fake_client import _FAKE_EXECUTIONS

        profile = build_trading_profile(_FAKE_EXECUTIONS, period_months=12)

        assert profile.total_executions == len(_FAKE_EXECUTIONS)
        assert profile.total_symbols_traded == 3  # AAPL, NVDA, TSLA
        assert profile.win_rate is not None
        # AAPL wins, NVDA loses → 50% win rate on 2 completed pairs
        assert profile.win_rate == pytest.approx(0.5)
        assert profile.concentration_score is not None
        assert profile.behavioral_flags is not None

    def test_empty_executions(self) -> None:
        profile = build_trading_profile([], period_months=12)
        assert profile.total_executions == 0
        assert profile.win_rate is None

    def test_per_symbol_stats(self) -> None:
        from broker.ibkr.fake_client import _FAKE_EXECUTIONS

        profile = build_trading_profile(_FAKE_EXECUTIONS)
        assert "AAPL" in profile.per_symbol_stats
        aapl = profile.per_symbol_stats["AAPL"]
        assert isinstance(aapl, dict)
        assert aapl["completed_trades"] == 1
        assert aapl["win_rate"] == pytest.approx(1.0)  # AAPL won

    def test_behavioral_flags_low_win_rate(self) -> None:
        execs = [
            _exec("b1", "A", "BUY", 10, 100, 0),
            _exec("s1", "A", "SELL", 10, 80, 30),   # loser
            _exec("b2", "B", "BUY", 10, 100, 5),
            _exec("s2", "B", "SELL", 10, 75, 35),   # loser
            _exec("b3", "C", "BUY", 10, 100, 10),
            _exec("s3", "C", "SELL", 10, 115, 40),  # winner
        ]
        profile = build_trading_profile(execs)
        # 2 losers, 1 winner → win_rate ≈ 0.33 → LOW_WIN_RATE
        assert "LOW_WIN_RATE" in profile.behavioral_flags
