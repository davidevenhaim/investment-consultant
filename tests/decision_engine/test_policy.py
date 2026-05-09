"""Tests for the deterministic risk policy engine."""

from db.enums import RecommendationAction
from decision_engine.policy import PolicyResult, apply_policy


def _call(
    action: RecommendationAction = RecommendationAction.BUY_CANDIDATE,
    confidence: float = 0.80,
    data_quality: float = 0.95,
    fdq: float = 0.85,
    completed: list | None = None,
    missing: list | None = None,
    has_position: bool = False,
    current_weight: float = 0.0,
    config: dict | None = None,
) -> PolicyResult:
    if completed is None:
        completed = ["market_data", "technical_signals", "price_risk", "fundamentals", "valuation"]
    if missing is None:
        missing = ["news", "portfolio_context"]
    return apply_policy(
        action=action,
        confidence=confidence,
        data_quality_score=data_quality,
        fundamentals_data_quality=fdq,
        completed_components=completed,
        missing_components=missing,
        has_position=has_position,
        current_position_weight=current_weight,
        strategy_config=config,
    )


# ── No gates triggered ────────────────────────────────────────────────────────


def test_clean_buy_passes_through() -> None:
    result = _call(action=RecommendationAction.BUY_CANDIDATE)
    assert result.final_action == RecommendationAction.BUY_CANDIDATE
    assert result.action_cap_applied is None


def test_hold_unaffected_by_policy() -> None:
    result = _call(action=RecommendationAction.HOLD)
    assert result.final_action == RecommendationAction.HOLD


# ── Confidence gate ───────────────────────────────────────────────────────────


def test_low_confidence_blocks_buy() -> None:
    result = _call(confidence=0.50)
    assert result.final_action == RecommendationAction.WATCHLIST
    assert any(c["gate"] == "min_confidence" and c["triggered"] for c in result.policy_checks)


def test_confidence_exactly_at_threshold_passes() -> None:
    result = _call(confidence=0.65)
    assert result.final_action == RecommendationAction.BUY_CANDIDATE


# ── Data quality gates ────────────────────────────────────────────────────────


def test_low_data_quality_blocks_buy() -> None:
    result = _call(data_quality=0.30)
    assert result.final_action == RecommendationAction.WATCHLIST


def test_moderate_data_quality_allows_buy_candidate() -> None:
    # 0.55 >= minimum_to_recommend (0.50) but < minimum_to_buy (0.75)
    # Should still allow BUY_CANDIDATE; STRONG_BUY blocked
    result = _call(action=RecommendationAction.BUY_CANDIDATE, data_quality=0.55)
    assert result.final_action == RecommendationAction.BUY_CANDIDATE


def test_low_data_quality_blocks_strong_buy_not_buy() -> None:
    # 0.55 < minimum_to_buy (0.75) — STRONG_BUY should be capped
    result = _call(action=RecommendationAction.STRONG_BUY, data_quality=0.55)
    assert result.final_action == RecommendationAction.BUY_CANDIDATE


# ── Fundamentals quality gate ─────────────────────────────────────────────────


def test_low_fundamentals_quality_caps_buy() -> None:
    result = _call(fdq=0.10)
    assert result.final_action == RecommendationAction.WATCHLIST
    assert any(
        c["gate"] == "low_fundamentals_quality" and c["triggered"] for c in result.policy_checks
    )


def test_moderate_fundamentals_quality_ok() -> None:
    result = _call(fdq=0.50)
    assert result.final_action == RecommendationAction.BUY_CANDIDATE


# ── Missing components gates ──────────────────────────────────────────────────


def test_missing_news_caps_strong_buy() -> None:
    result = _call(
        action=RecommendationAction.STRONG_BUY,
        missing=["news", "portfolio_context"],
        data_quality=0.95,
        fdq=0.90,
        confidence=0.92,
    )
    assert result.final_action == RecommendationAction.BUY_CANDIDATE
    assert any(c["gate"] == "missing_news" and c["triggered"] for c in result.policy_checks)


def test_missing_portfolio_caps_strong_buy() -> None:
    result = _call(
        action=RecommendationAction.STRONG_BUY,
        missing=["portfolio_context"],
        data_quality=0.95,
        fdq=0.90,
        confidence=0.92,
    )
    assert result.final_action == RecommendationAction.BUY_CANDIDATE


def test_buy_candidate_unaffected_by_missing_news() -> None:
    result = _call(
        action=RecommendationAction.BUY_CANDIDATE,
        missing=["news", "portfolio_context"],
    )
    assert result.final_action == RecommendationAction.BUY_CANDIDATE


# ── Position weight gate ──────────────────────────────────────────────────────


def test_overweight_position_blocks_buy() -> None:
    result = _call(current_weight=0.20, has_position=True)
    assert result.final_action == RecommendationAction.HOLD
    assert any(c["gate"] == "max_position_weight" and c["triggered"] for c in result.policy_checks)


def test_position_at_max_weight_passes() -> None:
    result = _call(current_weight=0.14)
    assert result.final_action == RecommendationAction.BUY_CANDIDATE


# ── Strategy config thresholds ────────────────────────────────────────────────


def test_custom_config_thresholds_used() -> None:
    config = {
        "confidence_thresholds": {"minimum_to_buy": 0.80},
        "data_quality_thresholds": {"minimum_to_buy": 0.90, "minimum_to_recommend": 0.60},
        "risk_policy": {"max_single_stock_weight": 0.10},
        "action_caps": {"missing_news": "BUY_CANDIDATE"},
    }
    # confidence 0.75 < custom threshold 0.80
    result = _call(confidence=0.75, config=config)
    assert result.final_action == RecommendationAction.WATCHLIST


# ── Policy check structure ────────────────────────────────────────────────────


def test_policy_result_has_all_expected_gates() -> None:
    result = _call()
    gate_names = {c["gate"] for c in result.policy_checks}
    assert "min_confidence" in gate_names
    assert "max_position_weight" in gate_names
    assert "missing_news" in gate_names
    assert "low_market_data_quality" in gate_names


def test_original_action_preserved_in_result() -> None:
    result = _call(action=RecommendationAction.STRONG_BUY, missing=["news"])
    assert result.original_action == RecommendationAction.STRONG_BUY
