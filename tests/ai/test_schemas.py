"""Tests for LLM output schemas — validation, forbidden fields, penalty caps."""
import pytest
from ai.schemas import (
    CombinedLLMAnalysis,
    CriticReview,
    MissingDetailsAnalysis,
    RiskAnalysis,
    ThesisAnalysis,
    check_forbidden_keys,
    empty_analysis,
)
from pydantic import ValidationError


def _thesis(**kwargs) -> dict:
    base = {
        "symbol": "AAPL",
        "short_thesis": "Strong fundamentals.",
        "bullish_points": ["Good margins"],
        "bearish_points": ["High valuation"],
        "what_changed_since_last_run": [],
        "previous_thesis_alignment": "UNCHANGED",
        "confidence": 0.8,
    }
    return {**base, **kwargs}


def _risk(**kwargs) -> dict:
    base = {
        "symbol": "AAPL",
        "key_risks": ["Valuation risk"],
        "valuation_risks": [],
        "business_risks": [],
        "technical_risks": [],
        "near_term_watch_items": [],
        "confidence": 0.75,
    }
    return {**base, **kwargs}


def _missing(**kwargs) -> dict:
    base = {
        "symbol": "AAPL",
        "blocking_missing_details": [],
        "non_blocking_missing_details": ["No news"],
        "should_reduce_confidence": False,
        "confidence_penalty": 0.05,
        "confidence": 0.85,
    }
    return {**base, **kwargs}


def _critic(**kwargs) -> dict:
    base = {
        "symbol": "AAPL",
        "strongest_counterargument": "Valuation stretched.",
        "weak_points_in_analysis": [],
        "potential_overclaims": [],
        "should_cap_strong_buy": False,
        "should_reduce_confidence": False,
        "confidence_penalty": 0.03,
        "confidence": 0.80,
    }
    return {**base, **kwargs}


def test_thesis_validates_good_payload() -> None:
    t = ThesisAnalysis.model_validate(_thesis())
    assert t.symbol == "AAPL"
    assert t.confidence == 0.8


def test_thesis_rejects_extra_action_field() -> None:
    with pytest.raises(ValidationError):
        ThesisAnalysis.model_validate(_thesis(action="STRONG_BUY"))


def test_thesis_rejects_extra_score_field() -> None:
    with pytest.raises(ValidationError):
        ThesisAnalysis.model_validate(_thesis(score=90))


def test_thesis_rejects_recommendation_field() -> None:
    with pytest.raises(ValidationError):
        ThesisAnalysis.model_validate(_thesis(recommendation="BUY"))


def test_risk_validates_good_payload() -> None:
    r = RiskAnalysis.model_validate(_risk())
    assert r.symbol == "AAPL"


def test_risk_rejects_extra_fields() -> None:
    with pytest.raises(ValidationError):
        RiskAnalysis.model_validate(_risk(hold="yes"))


def test_missing_confidence_penalty_capped_at_015() -> None:
    with pytest.raises(ValidationError):
        MissingDetailsAnalysis.model_validate(_missing(confidence_penalty=0.20))


def test_missing_confidence_penalty_max_015_passes() -> None:
    m = MissingDetailsAnalysis.model_validate(_missing(confidence_penalty=0.15))
    assert m.confidence_penalty == 0.15


def test_critic_confidence_penalty_capped_at_015() -> None:
    with pytest.raises(ValidationError):
        CriticReview.model_validate(_critic(confidence_penalty=0.16))


def test_critic_rejects_buy_sell_hold_fields() -> None:
    with pytest.raises(ValidationError):
        CriticReview.model_validate(_critic(buy="yes"))


def test_check_forbidden_keys_detects_action() -> None:
    raw = {"thesis": {"action": "STRONG_BUY", "symbol": "AAPL"}}
    assert "action" in check_forbidden_keys(raw)


def test_check_forbidden_keys_detects_score() -> None:
    raw = {"critic": {"score": 90}}
    assert "score" in check_forbidden_keys(raw)


def test_check_forbidden_keys_clean_returns_empty() -> None:
    raw = {"thesis": {"symbol": "AAPL", "short_thesis": "ok"}}
    assert check_forbidden_keys(raw) == []


def test_total_confidence_penalty_capped_at_025() -> None:
    with pytest.raises(ValidationError):
        CombinedLLMAnalysis(
            thesis=ThesisAnalysis.model_validate(_thesis()),
            risk=RiskAnalysis.model_validate(_risk()),
            missing_details=MissingDetailsAnalysis.model_validate(_missing()),
            critic=CriticReview.model_validate(_critic()),
            llm_enabled=True,
            total_confidence_penalty=0.30,  # over cap
            analysis_quality_score=0.8,
        )


def test_empty_analysis_is_valid() -> None:
    ea = empty_analysis("AAPL")
    assert ea.llm_enabled is False
    assert ea.total_confidence_penalty == 0.0
    assert ea.thesis.symbol == "AAPL"


def test_empty_analysis_has_no_forbidden_fields() -> None:
    import json
    ea = empty_analysis("AAPL")
    dumped = json.dumps(ea.model_dump())
    assert '"action"' not in dumped
    assert '"score"' not in dumped
    assert '"recommendation"' not in dumped
