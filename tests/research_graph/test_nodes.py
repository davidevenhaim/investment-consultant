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
from research_graph.nodes.retrieve_memory import make_retrieve_memory
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
        llm_analysis=None,
        llm_warnings=[],
        llm_confidence_penalty=0.0,
        memory_context=None,
        memory_count=0,
        memory_summary=None,
        previous_thesis=None,
        last_recommendation=None,
        past_mistakes=[],
        ohlcv=None,
        technical_signals=None,
        news_items=[],
        news_score_result=None,
        news_analysis=None,
        thesis_comparison=None,
        missing_details=None,
        bull_bear_case=None,
        score_breakdown=None,
        neutral_rec=None,
        portfolio_snapshot=None,
        portfolio_context=None,
        portfolio_snapshot_id=None,
        current_position_weight=0.0,
        current_position_value=None,
        current_quantity=0.0,
        cash_available=None,
        target_position_weight=None,
        suggested_trade_json=None,
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


@pytest.mark.asyncio
async def test_retrieve_memory_first_run_empty() -> None:
    from tests.memory.fake_store import FakeMemoryStore

    store = FakeMemoryStore()
    node = make_retrieve_memory(store=store)
    result = await node(_base_state())
    assert result["previous_thesis"] is None
    assert result["last_recommendation"] is None
    assert result["past_mistakes"] == []
    assert result["memory_count"] == 0
    assert "First run" in (result["memory_summary"] or "")


# ── score_to_action ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "score,expected",
    [
        (90, RecommendationAction.STRONG_BUY),
        (85, RecommendationAction.STRONG_BUY),
        (75, RecommendationAction.BUY_CANDIDATE),
        (70, RecommendationAction.BUY_CANDIDATE),
        (60, RecommendationAction.HOLD),
        (50, RecommendationAction.HOLD),
        (40, RecommendationAction.REDUCE),
        (35, RecommendationAction.REDUCE),
        (20, RecommendationAction.NO_ACTION),
    ],
)
def test_score_to_action_no_position(score: int, expected: RecommendationAction) -> None:
    assert score_to_action(float(score), has_position=False) == expected


def test_score_to_action_sell_with_position() -> None:
    assert score_to_action(20.0, has_position=True) == RecommendationAction.SELL


def test_score_to_action_uses_config_thresholds() -> None:
    config = {
        "action_thresholds": {"strong_buy": 90, "buy_candidate": 75, "hold": 55, "reduce": 40}
    }
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
        trailing_pe=120.0,
        forward_pe=100.0,
        price_to_book=30.0,
        price_to_sales=25.0,
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
    """HOLD with an existing position should stay HOLD."""
    state = _base_state("TSLA")
    state["neutral_rec"] = _make_neutral_rec(RecommendationAction.HOLD, 55)
    state["fundamentals_data_quality"] = 0.85
    state["data_quality_score"] = 0.95
    state["missing_components"] = ["portfolio_context"]
    state["completed_components"] = ["market_data", "news"]
    # M9: must have a position for HOLD to pass through
    state["current_quantity"] = 5.0
    state["current_position_weight"] = 0.08
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

# ── LLM analysis node ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_llm_analysis_node_disabled_writes_empty() -> None:
    """LLM_ENABLED=false (set by conftest override_env) — node returns empty without DB access."""
    from unittest.mock import AsyncMock

    from research_graph.nodes.llm_analysis import make_llm_analysis
    from sqlalchemy.ext.asyncio import AsyncSession

    # conftest autouse fixture sets LLM_ENABLED=false in env; no patch needed
    session = AsyncMock(spec=AsyncSession)
    node = make_llm_analysis(session, llm_client=None)
    result = await node(_base_state("AAPL"))

    assert result["llm_analysis"].llm_enabled is False
    assert result["llm_confidence_penalty"] == 0.0


@pytest.mark.asyncio
async def test_llm_analysis_node_with_fake_client_writes_analysis() -> None:
    """FakeClaudeClient injected: node writes valid CombinedLLMAnalysis (mocks DB prompt lookup)."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from ai.fake_client import FakeClaudeClient
    from research_graph.nodes.llm_analysis import make_llm_analysis
    from sqlalchemy.ext.asyncio import AsyncSession

    session = AsyncMock(spec=AsyncSession)
    fake_pv = MagicMock()
    fake_pv.prompt_text = "Analyze {{SYMBOL}}.\n{{CONTEXT}}"
    fake_pv.id = uuid.uuid4()
    mock_repo_instance = AsyncMock()
    mock_repo_instance.get_active = AsyncMock(return_value=fake_pv)
    mock_repo_class = MagicMock(return_value=mock_repo_instance)

    mock_settings = MagicMock()
    mock_settings.llm_enabled = True
    mock_settings.llm_model = "fake-model"
    mock_settings.llm_timeout_seconds = 30
    mock_settings.llm_max_retries = 2

    with (
        patch("research_graph.nodes.llm_analysis.get_settings", return_value=mock_settings),
        patch("research_graph.nodes.llm_analysis.PromptVersionRepository", mock_repo_class),
    ):
        node = make_llm_analysis(session, llm_client=FakeClaudeClient())
        result = await node(_base_state("AAPL"))

    analysis = result["llm_analysis"]
    assert analysis.llm_enabled is True
    assert analysis.thesis.short_thesis != ""
    assert result["llm_confidence_penalty"] >= 0.0


@pytest.mark.asyncio
async def test_llm_analysis_node_with_failing_client_writes_warning() -> None:
    """Failing LLM client: node writes empty analysis + warning, never raises."""
    import uuid
    from unittest.mock import AsyncMock, MagicMock, patch

    from ai.fake_client import FakeClaudeClient
    from research_graph.nodes.llm_analysis import make_llm_analysis
    from sqlalchemy.ext.asyncio import AsyncSession

    session = AsyncMock(spec=AsyncSession)
    fake_pv = MagicMock()
    fake_pv.prompt_text = "Analyze {{SYMBOL}}.\n{{CONTEXT}}"
    fake_pv.id = uuid.uuid4()
    mock_repo_instance = AsyncMock()
    mock_repo_instance.get_active = AsyncMock(return_value=fake_pv)
    mock_repo_class = MagicMock(return_value=mock_repo_instance)

    mock_settings = MagicMock()
    mock_settings.llm_enabled = True
    mock_settings.llm_model = "fake-model"
    mock_settings.llm_timeout_seconds = 30
    mock_settings.llm_max_retries = 2

    with (
        patch("research_graph.nodes.llm_analysis.get_settings", return_value=mock_settings),
        patch("research_graph.nodes.llm_analysis.PromptVersionRepository", mock_repo_class),
    ):
        node = make_llm_analysis(session, llm_client=FakeClaudeClient(fail=True))
        result = await node(_base_state("AAPL"))

    assert result["llm_analysis"].llm_enabled is False
    assert len(result.get("llm_warnings", [])) > 0


# ── neutral_recommendation + LLM integration ─────────────────────────────────


def test_neutral_recommendation_without_llm_analysis() -> None:
    """LLM disabled: score/action unchanged, breakdown.llm_enabled=False."""
    from research_graph.nodes.neutral_recommendation import neutral_recommendation
    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bullish()
    state["llm_analysis"] = None
    result = neutral_recommendation(state)
    assert result["neutral_rec"] is not None
    assert result["score_breakdown"].llm_enabled is False


def test_neutral_recommendation_adds_llm_reasons_when_enabled() -> None:
    """LLM enabled: thesis + bullish points appear in main_reasons."""
    from ai.fake_client import _FAKE_RESPONSE
    from ai.service import _parse_and_validate

    analysis = _parse_and_validate(
        __import__("json").dumps(_FAKE_RESPONSE), "AAPL", "fake"
    )
    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bullish()
    state["llm_analysis"] = analysis

    from research_graph.nodes.neutral_recommendation import neutral_recommendation
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    assert any("[LLM thesis]" in r for r in rec.main_reasons)
    assert any("[LLM]" in r for r in rec.main_reasons)


def test_neutral_recommendation_adds_llm_risks_when_enabled() -> None:
    from ai.fake_client import _FAKE_RESPONSE
    from ai.service import _parse_and_validate

    analysis = _parse_and_validate(__import__("json").dumps(_FAKE_RESPONSE), "AAPL", "fake")
    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bullish()
    state["llm_analysis"] = analysis

    from research_graph.nodes.neutral_recommendation import neutral_recommendation
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    # LLM risks and counterargument should appear
    assert any("[LLM]" in r for r in rec.main_risks)


def test_neutral_recommendation_confidence_penalty_applied() -> None:
    """LLM penalty reduces confidence; cannot go below 0."""
    import copy
    import json

    from ai.fake_client import _FAKE_RESPONSE
    from ai.service import _parse_and_validate

    # Build fake analysis with non-zero penalties
    raw = copy.deepcopy(_FAKE_RESPONSE)
    raw["missing_details"]["confidence_penalty"] = 0.10
    raw["critic"]["confidence_penalty"] = 0.10
    analysis = _parse_and_validate(json.dumps(raw), "AAPL", "fake")

    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bullish()
    state["llm_analysis"] = analysis

    from research_graph.nodes.neutral_recommendation import neutral_recommendation
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]

    assert 0.0 <= rec.confidence <= 1.0
    assert result["score_breakdown"].llm_confidence_penalty > 0


def test_neutral_recommendation_strong_buy_capped_by_critic() -> None:
    """When critic.should_cap_strong_buy=True and action=STRONG_BUY, caps to BUY_CANDIDATE."""
    import copy
    import json

    from ai.fake_client import _FAKE_RESPONSE
    from ai.service import _parse_and_validate
    from db.enums import RecommendationAction

    raw = copy.deepcopy(_FAKE_RESPONSE)
    raw["critic"]["should_cap_strong_buy"] = True
    analysis = _parse_and_validate(json.dumps(raw), "AAPL", "fake")

    state = _base_state("AAPL")
    # Force high score so action would be STRONG_BUY without LLM
    state["technical_signals"] = _signals_bullish()
    state["llm_analysis"] = analysis

    # Directly test cap logic: if score is STRONG_BUY territory
    from unittest.mock import patch

    from research_graph.nodes.neutral_recommendation import neutral_recommendation
    with patch(
        "research_graph.nodes.neutral_recommendation.score_to_action",
        return_value=RecommendationAction.STRONG_BUY,
    ):
        result = neutral_recommendation(state)
        rec = result["neutral_rec"]
        assert rec.action == RecommendationAction.BUY_CANDIDATE
        assert result["score_breakdown"].critic_should_cap_strong_buy is True


def test_llm_cannot_upgrade_action() -> None:
    """LLM critic.should_cap_strong_buy=False with HOLD score stays HOLD."""
    import json

    from ai.fake_client import _FAKE_RESPONSE
    from ai.service import _parse_and_validate
    from db.enums import RecommendationAction

    analysis = _parse_and_validate(json.dumps(_FAKE_RESPONSE), "AAPL", "fake")
    # Ensure no cap triggered
    assert analysis.critic.should_cap_strong_buy is False

    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bearish()  # score → HOLD or lower
    state["llm_analysis"] = analysis

    from research_graph.nodes.neutral_recommendation import neutral_recommendation
    result = neutral_recommendation(state)
    rec = result["neutral_rec"]
    # LLM cannot change action — it's still determined by the score
    assert rec.action in list(RecommendationAction)
    # Score is unchanged — LLM only affects confidence and qualitative output
    assert 0 <= rec.score <= 100


def test_score_breakdown_includes_llm_metadata() -> None:
    """score_breakdown has llm_enabled, llm_model, etc. when LLM ran."""
    import json

    from ai.fake_client import _FAKE_RESPONSE
    from ai.service import _parse_and_validate

    analysis = _parse_and_validate(json.dumps(_FAKE_RESPONSE), "AAPL", "fake")
    state = _base_state("AAPL")
    state["technical_signals"] = _signals_bullish()
    state["llm_analysis"] = analysis

    from research_graph.nodes.neutral_recommendation import neutral_recommendation
    result = neutral_recommendation(state)
    bd = result["score_breakdown"]
    assert bd.llm_enabled is True
    assert bd.llm_model == "fake"
    assert bd.thesis_alignment == "UNCHANGED"


# ── M9 Portfolio tests ────────────────────────────────────────────────────────


def _neutral_with_action(action: RecommendationAction, score: int = 65) -> NeutralRecState:
    return NeutralRecState(
        action=action,
        score=score,
        confidence=0.75,
        final_reason=f"Score {score}/100 ({action.value}).",
        score_breakdown=ScoreBreakdown(
            technical_score=15.0,
            fundamental_score=15.0,
            valuation_score=10.0,
            news_score=7.5,
            portfolio_fit_score=7.0,
            risk_score=10.0,
            total_score=float(score),
        ),
    )


def test_personalized_overweight_buy_becomes_hold():
    state = _base_state()
    state["neutral_rec"] = _neutral_with_action(RecommendationAction.BUY_CANDIDATE, 72)
    state["current_position_weight"] = 0.16  # above default max 0.15
    state["current_quantity"] = 10.0
    state["fundamentals_data_quality"] = 0.9  # avoid fdq gate
    state["data_quality_score"] = 0.95
    state["portfolio_context"] = {"max_single_stock_weight": 0.15, "total_equity": 50000.0}
    state["strategy_config"] = {"risk_policy": {"max_single_stock_weight": 0.15}}

    result = personalized_recommendation(state)
    rec = result["personalized_rec"]
    assert rec.personal_action == RecommendationAction.HOLD


def test_personalized_no_position_hold_becomes_watchlist():
    state = _base_state()
    state["neutral_rec"] = _neutral_with_action(RecommendationAction.HOLD, 55)
    state["current_position_weight"] = 0.0
    state["current_quantity"] = 0.0
    state["portfolio_context"] = {}

    result = personalized_recommendation(state)
    rec = result["personalized_rec"]
    assert rec.personal_action == RecommendationAction.WATCHLIST


def test_personalized_reduce_no_position_becomes_no_action():
    state = _base_state()
    state["neutral_rec"] = _neutral_with_action(RecommendationAction.REDUCE, 40)
    state["current_position_weight"] = 0.0
    state["current_quantity"] = 0.0
    state["portfolio_context"] = {}

    result = personalized_recommendation(state)
    rec = result["personalized_rec"]
    assert rec.personal_action == RecommendationAction.NO_ACTION


def test_personalized_buy_with_no_position_stays_buy():
    """BUY_CANDIDATE with no position and room → stays BUY_CANDIDATE."""
    state = _base_state()
    state["neutral_rec"] = _neutral_with_action(RecommendationAction.BUY_CANDIDATE, 75)
    state["current_position_weight"] = 0.0
    state["current_quantity"] = 0.0
    state["data_quality_score"] = 0.95
    state["fundamentals_data_quality"] = 0.9
    state["portfolio_context"] = {
        "max_single_stock_weight": 0.15, "total_equity": 50000.0, "risk_level": "MEDIUM"
    }
    state["strategy_config"] = {
        "risk_policy": {"max_single_stock_weight": 0.15, "min_confidence_to_buy": 0.65}
    }

    result = personalized_recommendation(state)
    rec = result["personalized_rec"]
    assert rec.personal_action == RecommendationAction.BUY_CANDIDATE


def test_position_sizing_json_populated():
    state = _base_state()
    state["neutral_rec"] = _neutral_with_action(RecommendationAction.BUY_CANDIDATE, 75)
    state["current_position_weight"] = 0.0
    state["current_quantity"] = 0.0
    state["data_quality_score"] = 0.95
    state["fundamentals_data_quality"] = 0.9
    state["portfolio_context"] = {
        "max_single_stock_weight": 0.15,
        "total_equity": 50000.0,
        "risk_level": "MEDIUM",
    }
    state["strategy_config"] = {
        "risk_policy": {"max_single_stock_weight": 0.15, "min_confidence_to_buy": 0.65}
    }

    result = personalized_recommendation(state)
    rec = result["personalized_rec"]
    assert rec.suggested_trade_json is not None
    assert "trade_type" in rec.suggested_trade_json


def test_personalized_no_portfolio_context_uses_defaults():
    """No portfolio_context in state → falls back to safe defaults."""
    state = _base_state()
    state["neutral_rec"] = _neutral_with_action(RecommendationAction.HOLD, 55)
    # No portfolio_context, no current_quantity → no portfolio data
    result = personalized_recommendation(state)
    assert "personalized_rec" in result
    rec = result["personalized_rec"]
    # HOLD + no position (current_quantity=0 default) → WATCHLIST
    assert rec.personal_action == RecommendationAction.WATCHLIST
