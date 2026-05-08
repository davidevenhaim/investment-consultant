"""Unit tests for individual graph nodes — no DB required for scoring nodes."""
from datetime import UTC, datetime
from typing import Any

import pytest
from db.enums import RecommendationAction
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


def _signals_bullish() -> dict[str, Any]:
    """Realistic M4 signals for a bullish stock."""
    return {
        "latest_close": 175.0,
        "price_vs_sma_200": 1.08,
        "price_vs_sma_50": 1.03,
        "return_3m": 0.12,
        "return_6m": 0.18,
        "relative_strength_3m_vs_spy": 0.05,
        "rsi_14": 58.0,
        "volatility_90d": 0.22,
        "atr_14_pct": 0.016,
        "max_drawdown_1y": -0.12,
    }


def _signals_bearish() -> dict[str, Any]:
    return {
        "latest_close": 90.0,
        "price_vs_sma_200": 0.93,
        "price_vs_sma_50": 0.95,
        "return_3m": -0.08,
        "return_6m": -0.15,
        "relative_strength_3m_vs_spy": -0.06,
        "rsi_14": 38.0,
        "volatility_90d": 0.48,
        "atr_14_pct": 0.042,
        "max_drawdown_1y": -0.38,
    }


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


# ── score_to_action ───────────────────────────────────────────────────────────

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


# ── _technical_score (M4 signals) ─────────────────────────────────────────────

def test_technical_score_bullish() -> None:
    score = _technical_score(_signals_bullish())
    assert 14 <= score <= 20


def test_technical_score_bearish() -> None:
    score = _technical_score(_signals_bearish())
    assert 0 <= score <= 4


def test_technical_score_empty_signals_returns_zero() -> None:
    assert _technical_score({}) == 0.0


# ── _risk_score (M4 signals) ──────────────────────────────────────────────────

def test_risk_score_bullish() -> None:
    score = _risk_score(_signals_bullish())
    assert 8 <= score <= 15


def test_risk_score_bearish() -> None:
    score = _risk_score(_signals_bearish())
    assert 0 <= score <= 5


def test_risk_score_low_volatility_atr_fallback() -> None:
    assert _risk_score({"atr_pct": 0.008}) > 0


def test_risk_score_high_volatility_atr_fallback() -> None:
    assert _risk_score({"atr_pct": 0.07}) < 5


# ── neutral_recommendation ────────────────────────────────────────────────────

def test_neutral_recommendation_bullish_score_above_70() -> None:
    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bullish()
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    assert rec is not None
    assert rec.score >= 70
    assert rec.action in (RecommendationAction.BUY_CANDIDATE, RecommendationAction.STRONG_BUY)


def test_neutral_recommendation_bearish_score_below_60() -> None:
    state = _base_state("TSLA")
    state["technical_signals"] = _signals_bearish()
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    assert rec is not None
    assert rec.score < 60


def test_neutral_recommendation_score_in_bounds() -> None:
    state = _base_state("NVDA")
    state["technical_signals"] = _signals_bullish()
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    assert rec is not None
    assert 0 <= rec.score <= 100


def test_neutral_recommendation_returns_score_breakdown() -> None:
    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bullish()
    result = neutral_recommendation(state)
    assert result.get("score_breakdown") is not None


def test_neutral_recommendation_missing_signals_degrades_gracefully() -> None:
    state = _base_state("AAPL")
    state["technical_signals"] = None
    result = neutral_recommendation(state)
    assert result.get("neutral_rec") is not None


def test_neutral_recommendation_final_reason_mentions_m4() -> None:
    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bullish()
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    assert rec is not None
    assert "real M4 data" in rec.final_reason


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
    nr.confidence = 0.50
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
