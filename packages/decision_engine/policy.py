"""Deterministic risk policy engine. No LLM, no randomness.

Applies hard gates and soft caps to the neutral recommendation action.
All logic here is auditable and testable without any external services.
"""
from typing import Any

from core.logging import get_logger
from db.enums import RecommendationAction

logger = get_logger(__name__)

_BUY_ACTIONS = frozenset({RecommendationAction.STRONG_BUY, RecommendationAction.BUY_CANDIDATE})
_STRONG_BUY_ONLY = frozenset({RecommendationAction.STRONG_BUY})

_DEFAULT_MAX_POSITION_WEIGHT = 0.15
_DEFAULT_MIN_CONFIDENCE = 0.65
_DEFAULT_MIN_DATA_QUALITY_TO_BUY = 0.75
_DEFAULT_MIN_DATA_QUALITY_TO_RECOMMEND = 0.50
_DEFAULT_MIN_FUNDAMENTALS_QUALITY = 0.30


def _is_buy(action: RecommendationAction) -> bool:
    return action in _BUY_ACTIONS


def _is_strong_buy(action: RecommendationAction) -> bool:
    return action in _STRONG_BUY_ONLY


class PolicyResult:
    def __init__(
        self,
        original_action: RecommendationAction,
        final_action: RecommendationAction,
        policy_checks: list[dict[str, Any]],
        action_cap_applied: str | None,
        reasons: list[str],
    ) -> None:
        self.original_action = original_action
        self.final_action = final_action
        self.policy_checks = policy_checks
        self.action_cap_applied = action_cap_applied
        self.reasons = reasons


def apply_policy(
    action: RecommendationAction,
    confidence: float,
    data_quality_score: float,
    fundamentals_data_quality: float,
    completed_components: list[str],
    missing_components: list[str],
    has_position: bool = False,
    current_position_weight: float = 0.0,
    strategy_config: dict[str, Any] | None = None,
) -> PolicyResult:
    """
    Apply deterministic policy gates.
    Returns PolicyResult with final action, all checks, and reasons.
    """
    cfg = strategy_config or {}
    conf_thresh = cfg.get("confidence_thresholds", {}).get(
        "minimum_to_buy", _DEFAULT_MIN_CONFIDENCE
    )
    dq_thresh_buy = cfg.get("data_quality_thresholds", {}).get(
        "minimum_to_buy", _DEFAULT_MIN_DATA_QUALITY_TO_BUY
    )
    dq_thresh_rec = cfg.get("data_quality_thresholds", {}).get(
        "minimum_to_recommend", _DEFAULT_MIN_DATA_QUALITY_TO_RECOMMEND
    )
    max_weight = cfg.get("risk_policy", {}).get(
        "max_single_stock_weight", _DEFAULT_MAX_POSITION_WEIGHT
    )
    action_caps = cfg.get("action_caps", {})

    current = action
    checks: list[dict[str, Any]] = []
    cap_applied: str | None = None
    reasons: list[str] = []

    # Gate 1: market data quality too low → WATCHLIST
    if data_quality_score < dq_thresh_rec and _is_buy(current):
        current = RecommendationAction.WATCHLIST
        cap_applied = "low_market_data_quality"
        checks.append({
            "gate": "low_market_data_quality",
            "triggered": True,
            "reason": f"Market data quality {data_quality_score:.2f} < {dq_thresh_rec:.2f}",
        })
        reasons.append(f"Insufficient market data quality ({data_quality_score:.0%}).")
    else:
        checks.append({
            "gate": "low_market_data_quality",
            "triggered": False,
            "data_quality_score": data_quality_score,
            "threshold": dq_thresh_rec,
        })

    # Gate 2: fundamentals quality too low → WATCHLIST (for buy actions)
    fdq_thresh = _DEFAULT_MIN_FUNDAMENTALS_QUALITY
    if fundamentals_data_quality < fdq_thresh and _is_buy(current):
        cap_value = action_caps.get("low_fundamentals_quality", "WATCHLIST")
        capped = RecommendationAction(cap_value)
        if _action_rank(capped) < _action_rank(current):
            current = capped
            cap_applied = "low_fundamentals_quality"
        checks.append({
            "gate": "low_fundamentals_quality",
            "triggered": True,
            "reason": (
                f"Fundamentals data quality {fundamentals_data_quality:.2f} < {fdq_thresh:.2f}"
            ),
        })
        reasons.append(f"Insufficient fundamentals data quality ({fundamentals_data_quality:.0%}).")
    else:
        checks.append({
            "gate": "low_fundamentals_quality",
            "triggered": False,
            "fundamentals_data_quality": fundamentals_data_quality,
            "threshold": fdq_thresh,
        })

    # Gate 3: min confidence to buy
    if confidence < conf_thresh and _is_buy(current):
        current = RecommendationAction.WATCHLIST
        cap_applied = cap_applied or "low_confidence"
        checks.append({
            "gate": "min_confidence",
            "triggered": True,
            "reason": f"Confidence {confidence:.2f} < threshold {conf_thresh:.2f}",
        })
        reasons.append(f"Confidence {confidence:.0%} below minimum to buy.")
    else:
        checks.append({
            "gate": "min_confidence",
            "triggered": False,
            "confidence": confidence,
            "threshold": conf_thresh,
        })

    # Gate 4: market data quality gate for strong buy (higher bar)
    if data_quality_score < dq_thresh_buy and _is_strong_buy(current):
        current = RecommendationAction.BUY_CANDIDATE
        cap_applied = cap_applied or "insufficient_data_for_strong_buy"
        checks.append({
            "gate": "min_data_quality_strong_buy",
            "triggered": True,
            "reason": f"Data quality {data_quality_score:.2f} < {dq_thresh_buy:.2f} for STRONG_BUY",
        })

    # Gate 5: missing news → cap STRONG_BUY at BUY_CANDIDATE
    news_missing = "news" in missing_components
    if news_missing and _is_strong_buy(current):
        cap_value = action_caps.get("missing_news", "BUY_CANDIDATE")
        capped = RecommendationAction(cap_value)
        if _action_rank(capped) < _action_rank(current):
            current = capped
            cap_applied = cap_applied or "missing_news"
        checks.append({
            "gate": "missing_news",
            "triggered": True,
            "reason": "News analysis not yet available — STRONG_BUY capped at BUY_CANDIDATE",
        })
        reasons.append("News analysis missing. Action capped below STRONG_BUY.")
    else:
        checks.append({"gate": "missing_news", "triggered": False, "news_missing": news_missing})

    # Gate 6: missing portfolio context → cap STRONG_BUY at BUY_CANDIDATE
    port_missing = "portfolio_context" in missing_components
    if port_missing and _is_strong_buy(current):
        cap_value = action_caps.get("missing_portfolio_context", "BUY_CANDIDATE")
        capped = RecommendationAction(cap_value)
        if _action_rank(capped) < _action_rank(current):
            current = capped
            cap_applied = cap_applied or "missing_portfolio_context"
        checks.append({
            "gate": "missing_portfolio_context",
            "triggered": True,
            "reason": "Portfolio context not yet available — STRONG_BUY capped",
        })
    else:
        checks.append({
            "gate": "missing_portfolio_context",
            "triggered": False,
            "portfolio_context_missing": port_missing,
        })

    # Gate 7: position overweight → downgrade buy
    if current_position_weight > max_weight and _is_buy(current):
        current = RecommendationAction.HOLD
        cap_applied = cap_applied or "position_overweight"
        checks.append({
            "gate": "max_position_weight",
            "triggered": True,
            "reason": (
                f"Position weight {current_position_weight:.0%} > max {max_weight:.0%}"
            ),
        })
        reasons.append(
            f"Position already at {current_position_weight:.0%} (max {max_weight:.0%})."
        )
    else:
        checks.append({
            "gate": "max_position_weight",
            "triggered": False,
            "current": current_position_weight,
            "max": max_weight,
        })

    return PolicyResult(
        original_action=action,
        final_action=current,
        policy_checks=checks,
        action_cap_applied=cap_applied,
        reasons=reasons,
    )


_ACTION_RANK: dict[RecommendationAction, int] = {
    RecommendationAction.NO_ACTION: 0,
    RecommendationAction.WATCHLIST: 1,
    RecommendationAction.SELL: 2,
    RecommendationAction.REDUCE: 3,
    RecommendationAction.HOLD: 4,
    RecommendationAction.BUY_CANDIDATE: 5,
    RecommendationAction.STRONG_BUY: 6,
}


def _action_rank(action: RecommendationAction) -> int:
    """Lower rank = weaker action."""
    return _ACTION_RANK.get(action, 0)
