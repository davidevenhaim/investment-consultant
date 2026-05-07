"""Unit tests for individual graph nodes — no DB required."""
from datetime import UTC, datetime

import pytest
from db.enums import RecommendationAction
from research_graph.nodes.compute_signals import _DEFAULT_SIGNALS, _MOCK_SIGNALS, compute_signals
from research_graph.nodes.fetch_market_data import fetch_market_data
from research_graph.nodes.load_ticker_context import load_ticker_context
from research_graph.nodes.neutral_recommendation import (
    _risk_score,
    _technical_score,
    neutral_recommendation,
    score_to_action,
)
from research_graph.nodes.personalized_recommendation import personalized_recommendation
from research_graph.nodes.retrieve_memory import retrieve_memory
from research_graph.state import NeutralRecState, ResearchState, ScoreBreakdown


def _base_state(symbol: str = "AAPL") -> ResearchState:
    return ResearchState(
        run_id="00000000-0000-0000-0000-000000000001",
        run_ticker_id="00000000-0000-0000-0000-000000000002",
        symbol=symbol,
        as_of_time=datetime.now(UTC),
        strategy_version="v0.1.0",
        prompt_version="v0.1.0",
        previous_thesis=None,
        last_recommendation=None,
        past_mistakes=[],
        ohlcv=None,
        technical_signals=None,
        news_items=[],
        news_analysis=None,
        thesis_comparison=None,
        missing_details=None,
        bull_bear_case=None,
        score_breakdown=None,
        neutral_rec=None,
        portfolio_snapshot=None,
        personalized_rec=None,
        errors=[],
        data_quality_score=1.0,
        confidence_penalties=[],
    )


# ── load_ticker_context ───────────────────────────────────────────────────────


def test_load_ticker_context_sets_as_of_time() -> None:
    before = datetime.now(UTC)
    result = load_ticker_context(_base_state())
    assert "as_of_time" in result
    assert result["as_of_time"] >= before


# ── retrieve_memory ───────────────────────────────────────────────────────────


def test_retrieve_memory_returns_empty_stubs() -> None:
    result = retrieve_memory(_base_state())
    assert result["previous_thesis"] is None
    assert result["last_recommendation"] is None
    assert result["past_mistakes"] == []


# ── fetch_market_data ─────────────────────────────────────────────────────────


def test_fetch_market_data_returns_dataframe_for_known_symbol() -> None:
    import pandas as pd
    result = fetch_market_data(_base_state("AAPL"))
    assert "ohlcv" in result
    assert isinstance(result["ohlcv"], pd.DataFrame)
    assert len(result["ohlcv"]) == 30


def test_fetch_market_data_returns_dataframe_for_unknown_symbol() -> None:
    import pandas as pd
    result = fetch_market_data(_base_state("UNKN"))
    assert isinstance(result["ohlcv"], pd.DataFrame)


def test_fetch_market_data_has_expected_columns() -> None:
    result = fetch_market_data(_base_state("NVDA"))
    cols = set(result["ohlcv"].columns)
    assert {"open", "high", "low", "close", "volume"}.issubset(cols)


# ── compute_signals ───────────────────────────────────────────────────────────


def test_compute_signals_returns_rsi_for_known_symbol() -> None:
    state = _base_state("AAPL")
    result = compute_signals(state)
    assert result["technical_signals"] is not None
    assert "rsi" in result["technical_signals"]
    assert result["technical_signals"]["rsi"] == _MOCK_SIGNALS["AAPL"]["rsi"]


def test_compute_signals_uses_default_for_unknown_symbol() -> None:
    state = _base_state("ZZZZ")
    result = compute_signals(state)
    assert result["technical_signals"] is not None
    assert result["technical_signals"]["rsi"] == _DEFAULT_SIGNALS["rsi"]


# ── score_to_action (scoring engine) ─────────────────────────────────────────


@pytest.mark.parametrize("score,expected", [
    (90, RecommendationAction.STRONG_BUY),
    (85, RecommendationAction.STRONG_BUY),
    (75, RecommendationAction.BUY_CANDIDATE),
    (70, RecommendationAction.BUY_CANDIDATE),
    (60, RecommendationAction.HOLD),
    (50, RecommendationAction.HOLD),
    (40, RecommendationAction.REDUCE),
    (35, RecommendationAction.REDUCE),
    (20, RecommendationAction.NO_ACTION),
])
def test_score_to_action_no_position(score: int, expected: RecommendationAction) -> None:
    assert score_to_action(float(score), has_position=False) == expected


def test_score_to_action_sell_with_position() -> None:
    assert score_to_action(20.0, has_position=True) == RecommendationAction.SELL


def test_technical_score_bullish() -> None:
    signals = {"rsi": 62.0, "macd_histogram": 0.5, "price_vs_ema20": 1.03, "momentum_1m": 0.06}
    score = _technical_score(signals)
    assert 12 <= score <= 20


def test_technical_score_bearish() -> None:
    signals = {"rsi": 35.0, "macd_histogram": -1.0, "price_vs_ema20": 0.95, "momentum_1m": -0.05}
    score = _technical_score(signals)
    assert 0 <= score <= 6


def test_risk_score_low_volatility() -> None:
    assert _risk_score({"atr_pct": 0.008}) == 15.0


def test_risk_score_high_volatility() -> None:
    assert _risk_score({"atr_pct": 0.07}) == 2.0


# ── neutral_recommendation ────────────────────────────────────────────────────


def test_neutral_recommendation_aapl_is_buy_candidate() -> None:
    state = _base_state("AAPL")
    state["technical_signals"] = dict(_MOCK_SIGNALS["AAPL"])
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    assert rec is not None
    assert rec.action == RecommendationAction.BUY_CANDIDATE
    assert 70 <= rec.score <= 84
    assert 0.0 < rec.confidence <= 1.0


def test_neutral_recommendation_tsla_is_hold() -> None:
    state = _base_state("TSLA")
    state["technical_signals"] = dict(_MOCK_SIGNALS["TSLA"])
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    assert rec is not None
    assert rec.action in (RecommendationAction.HOLD, RecommendationAction.REDUCE)
    assert rec.score < 70


def test_neutral_recommendation_score_bounds() -> None:
    state = _base_state("NVDA")
    state["technical_signals"] = dict(_MOCK_SIGNALS["NVDA"])
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    assert rec is not None
    assert 0 <= rec.score <= 100


def test_neutral_recommendation_returns_score_breakdown() -> None:
    state = _base_state("AAPL")
    state["technical_signals"] = dict(_MOCK_SIGNALS["AAPL"])
    result = neutral_recommendation(state)
    assert result.get("score_breakdown") is not None


def test_neutral_recommendation_missing_signals_degrades_gracefully() -> None:
    state = _base_state("AAPL")
    state["technical_signals"] = None
    result = neutral_recommendation(state)
    # Should still return a recommendation (using default signals of 0)
    assert result.get("neutral_rec") is not None


# ── personalized_recommendation ───────────────────────────────────────────────


def _make_neutral_rec(action: RecommendationAction, score: int) -> NeutralRecState:
    return NeutralRecState(
        action=action,
        score=score,
        confidence=0.75,
        final_reason="test",
        score_breakdown=ScoreBreakdown(total_score=float(score)),
    )


def test_personalized_passes_through_buy_candidate() -> None:
    state = _base_state("AAPL")
    state["neutral_rec"] = _make_neutral_rec(RecommendationAction.BUY_CANDIDATE, 73)
    result = personalized_recommendation(state)
    rec = result["personalized_rec"]
    assert rec is not None
    assert rec.personal_action == RecommendationAction.BUY_CANDIDATE


def test_personalized_passes_through_hold() -> None:
    state = _base_state("TSLA")
    state["neutral_rec"] = _make_neutral_rec(RecommendationAction.HOLD, 55)
    result = personalized_recommendation(state)
    rec = result["personalized_rec"]
    assert rec is not None
    assert rec.personal_action == RecommendationAction.HOLD


def test_personalized_low_confidence_triggers_watchlist() -> None:
    state = _base_state("AAPL")
    nr = _make_neutral_rec(RecommendationAction.BUY_CANDIDATE, 73)
    nr.confidence = 0.50  # below 0.65 threshold
    state["neutral_rec"] = nr
    result = personalized_recommendation(state)
    rec = result["personalized_rec"]
    assert rec is not None
    assert rec.personal_action == RecommendationAction.WATCHLIST


def test_personalized_no_neutral_adds_error() -> None:
    state = _base_state("AAPL")
    state["neutral_rec"] = None
    result = personalized_recommendation(state)
    assert "errors" in result
    assert len(result["errors"]) > 0
