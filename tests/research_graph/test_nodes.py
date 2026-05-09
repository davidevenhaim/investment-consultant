"""Unit tests for individual graph nodes — no DB required for scoring/policy nodes."""
from datetime import UTC, datetime
from typing import Any

import pytest
from db.enums import RecommendationAction
from research_graph.nodes.load_ticker_context import load_ticker_context
from research_graph.nodes.neutral_recommendation import (
    _fundamental_score,
    _risk_score,
    _technical_score,
    _valuation_score,
    neutral_recommendation,
    score_to_action,
)
from research_graph.nodes.personalized_recommendation import personalized_recommendation
from research_graph.nodes.retrieve_memory import retrieve_memory
from research_graph.state import NeutralRecState, ResearchState, ScoreBreakdown

from tests.fundamentals.conftest import _make_snapshot


def _base_state(symbol: str = "AAPL") -> ResearchState:
    return ResearchState(
        run_id="00000000-0000-0000-0000-000000000001",
        run_ticker_id="00000000-0000-0000-0000-000000000002",
        symbol=symbol,
        as_of_time=datetime.now(UTC),
        strategy_version="v0.1.0",
        prompt_version="v0.1.0",
        strategy_config={},
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
        fundamentals_snapshot=None,
        fundamentals_data_quality=0.0,
        analysis_completeness=0.0,
        completed_components=[],
        missing_components=[],
        errors=[],
        data_quality_score=1.0,
        confidence_penalties=[],
    )


def _signals_bullish() -> dict[str, Any]:
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


def test_score_to_action_uses_config_thresholds() -> None:
    config = {"action_thresholds": {"strong_buy": 90, "buy_candidate": 75, "hold": 55, "reduce": 40}}
    assert score_to_action(87.0, config=config) == RecommendationAction.BUY_CANDIDATE
    assert score_to_action(91.0, config=config) == RecommendationAction.STRONG_BUY


# ── _technical_score ──────────────────────────────────────────────────────────

def test_technical_score_bullish() -> None:
    score = _technical_score(_signals_bullish())
    assert 14 <= score <= 20


def test_technical_score_bearish() -> None:
    score = _technical_score(_signals_bearish())
    assert 0 <= score <= 4


def test_technical_score_empty_signals_returns_zero() -> None:
    assert _technical_score({}) == 0.0


# ── _risk_score ───────────────────────────────────────────────────────────────

def test_risk_score_bullish() -> None:
    assert 8 <= _risk_score(_signals_bullish()) <= 15


def test_risk_score_bearish() -> None:
    assert 0 <= _risk_score(_signals_bearish()) <= 5


def test_risk_score_low_volatility_atr_fallback() -> None:
    assert _risk_score({"atr_pct": 0.008}) > 0


# ── _fundamental_score ────────────────────────────────────────────────────────

def test_fundamental_score_strong_company() -> None:
    snap = _make_snapshot("AAPL")  # high margins, good growth, positive ROE
    score, reasons, risks = _fundamental_score(snap)
    assert score >= 12
    assert len(reasons) > 0


def test_fundamental_score_weak_company() -> None:
    snap = _make_snapshot(
        "WEAK",
        revenue_growth=-0.10,
        earnings_growth=-0.20,
        profit_margins=-0.02,
        return_on_equity=-0.05,
        debt_to_equity=3.0,
    )
    score, reasons, risks = _fundamental_score(snap)
    assert score <= 5
    assert len(risks) > 0


def test_fundamental_score_none_returns_zero() -> None:
    score, reasons, risks = _fundamental_score(None)
    assert score == 0.0
    assert len(risks) > 0


def test_fundamental_score_partial_fields() -> None:
    snap = _make_snapshot("X", revenue_growth=0.15, profit_margins=None, return_on_equity=None)
    score, _, _ = _fundamental_score(snap)
    assert 0 < score < 20


def test_fundamental_score_dte_low_scores_well() -> None:
    # 0.4x — strong balance sheet (provider already normalized)
    snap = _make_snapshot("X", debt_to_equity=0.4)
    score, reasons, _ = _fundamental_score(snap)
    assert any("Low debt-to-equity" in r for r in reasons)
    assert score >= 2  # earns the 2pt "low D/E" bonus


def test_fundamental_score_dte_nvda_like_is_low() -> None:
    # NVDA yfinance raw≈7.25 → normalized 0.0725x → "Low D/E" bucket
    snap = _make_snapshot("NVDA", debt_to_equity=0.0725)
    _, reasons, _ = _fundamental_score(snap)
    assert any("Low debt-to-equity" in r for r in reasons)


def test_fundamental_score_dte_aapl_like_is_moderate() -> None:
    # AAPL yfinance raw≈79.5 → normalized 0.795x → "Moderate D/E" bucket
    snap = _make_snapshot("AAPL", debt_to_equity=0.795)
    _, reasons, _ = _fundamental_score(snap)
    assert any("Moderate debt-to-equity" in r for r in reasons)


def test_fundamental_score_dte_high_is_flagged() -> None:
    # 3.5x — genuinely high leverage ratio
    snap = _make_snapshot("X", debt_to_equity=3.5)
    _, _, risks = _fundamental_score(snap)
    assert any("High debt-to-equity" in r for r in risks)


# ── _valuation_score ──────────────────────────────────────────────────────────

def test_valuation_score_reasonable() -> None:
    snap = _make_snapshot("AAPL", trailing_pe=20.0, forward_pe=18.0, price_to_book=3.0)
    score, reasons, _ = _valuation_score(snap)
    assert score >= 6


def test_valuation_score_expensive() -> None:
    snap = _make_snapshot(
        "PRICEY",
        trailing_pe=120.0, forward_pe=100.0,
        price_to_book=30.0, price_to_sales=25.0,
        revenue_growth=0.05,
    )
    score, _, risks = _valuation_score(snap)
    assert score <= 4
    assert len(risks) > 0


def test_valuation_score_growth_adjusted() -> None:
    # High PE but with 85% revenue growth (NVDA-like) should score better than same PE with 5% growth
    snap_growth = _make_snapshot("NVDA", trailing_pe=55.0, revenue_growth=0.85)
    snap_value = _make_snapshot("OLD", trailing_pe=55.0, revenue_growth=0.05)
    score_growth, _, _ = _valuation_score(snap_growth)
    score_value, _, _ = _valuation_score(snap_value)
    assert score_growth >= score_value


def test_valuation_score_none_returns_zero() -> None:
    score, _, risks = _valuation_score(None)
    assert score == 0.0
    assert len(risks) > 0


# ── neutral_recommendation (full node) ───────────────────────────────────────

def test_neutral_recommendation_bullish_with_fundamentals() -> None:
    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bullish()
    state["fundamentals_snapshot"] = _make_snapshot("AAPL")
    state["fundamentals_data_quality"] = 1.0
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    assert rec is not None
    assert rec.score >= 60


def test_neutral_recommendation_score_in_bounds() -> None:
    state = _base_state("NVDA")
    state["technical_signals"] = _signals_bullish()
    state["fundamentals_snapshot"] = _make_snapshot("NVDA")
    state["fundamentals_data_quality"] = 1.0
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    assert rec is not None
    assert 0 <= rec.score <= 100


def test_neutral_recommendation_returns_score_breakdown() -> None:
    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bullish()
    state["fundamentals_snapshot"] = _make_snapshot("AAPL")
    state["fundamentals_data_quality"] = 1.0
    result = neutral_recommendation(state)
    assert result.get("score_breakdown") is not None


def test_neutral_recommendation_missing_signals_degrades_gracefully() -> None:
    state = _base_state("AAPL")
    state["technical_signals"] = None
    state["fundamentals_snapshot"] = None
    result = neutral_recommendation(state)
    assert result.get("neutral_rec") is not None


def test_neutral_recommendation_final_reason_is_real_not_stub() -> None:
    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bullish()
    state["fundamentals_snapshot"] = _make_snapshot("AAPL")
    state["fundamentals_data_quality"] = 1.0
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    assert rec is not None
    assert "real" in rec.final_reason.lower()


def test_neutral_recommendation_missing_details_non_empty() -> None:
    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bullish()
    state["fundamentals_snapshot"] = _make_snapshot("AAPL")
    state["fundamentals_data_quality"] = 1.0
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    assert rec is not None
    assert len(rec.missing_details) >= 2


def test_neutral_recommendation_completeness_populated() -> None:
    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bullish()
    state["fundamentals_snapshot"] = _make_snapshot("AAPL")
    state["fundamentals_data_quality"] = 1.0
    result = neutral_recommendation(state)
    assert result.get("analysis_completeness") is not None
    assert result.get("completed_components") is not None
    assert result.get("missing_components") is not None
    assert "news" in result["missing_components"]


def test_neutral_recommendation_config_thresholds_respected() -> None:
    state = _base_state("AAPL")
    state["strategy_config"] = {
        "action_thresholds": {"strong_buy": 95, "buy_candidate": 80, "hold": 60, "reduce": 40},
        "stub_scores": {"news": 9, "portfolio_fit": 12},
    }
    state["technical_signals"] = _signals_bullish()
    state["fundamentals_snapshot"] = _make_snapshot("AAPL")
    state["fundamentals_data_quality"] = 1.0
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    assert rec is not None
    # With higher thresholds, same score maps to lower action
    assert rec.action in (
        RecommendationAction.HOLD,
        RecommendationAction.BUY_CANDIDATE,
        RecommendationAction.REDUCE,
    )


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
    state["fundamentals_data_quality"] = 0.85
    state["data_quality_score"] = 0.95
    state["missing_components"] = ["news", "portfolio_context"]
    state["completed_components"] = ["market_data", "technical_signals", "fundamentals"]
    result = personalized_recommendation(state)
    rec = result["personalized_rec"]
    assert rec is not None
    assert rec.personal_action == RecommendationAction.BUY_CANDIDATE


def test_personalized_passes_through_hold() -> None:
    state = _base_state("TSLA")
    state["neutral_rec"] = _make_neutral_rec(RecommendationAction.HOLD, 55)
    state["fundamentals_data_quality"] = 0.85
    state["data_quality_score"] = 0.95
    state["missing_components"] = ["news", "portfolio_context"]
    state["completed_components"] = ["market_data"]
    result = personalized_recommendation(state)
    rec = result["personalized_rec"]
    assert rec is not None
    assert rec.personal_action == RecommendationAction.HOLD


def test_personalized_low_confidence_triggers_watchlist() -> None:
    state = _base_state("AAPL")
    nr = _make_neutral_rec(RecommendationAction.BUY_CANDIDATE, 73)
    nr.confidence = 0.50
    state["neutral_rec"] = nr
    state["fundamentals_data_quality"] = 0.85
    state["data_quality_score"] = 0.95
    state["missing_components"] = ["news", "portfolio_context"]
    state["completed_components"] = ["market_data"]
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
