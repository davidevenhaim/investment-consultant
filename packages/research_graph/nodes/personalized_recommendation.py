"""PersonalizedRecommendation — apply risk policy to produce portfolio-aware action."""
from typing import Any

from core.logging import get_logger
from db.enums import RecommendationAction

from research_graph.state import PersonalizedRecState, ResearchState

logger = get_logger(__name__)

# Default policy thresholds (from default InvestorProfile seed data).
# M9 replaces these with live values from the IBKR portfolio snapshot.
_DEFAULT_MAX_SINGLE_STOCK_WEIGHT: float = 0.15
_DEFAULT_MIN_CONFIDENCE: float = 0.65
_DEFAULT_MIN_DATA_QUALITY: float = 0.50

_BUY_ACTIONS = frozenset({RecommendationAction.STRONG_BUY, RecommendationAction.BUY_CANDIDATE})


def _is_buy_action(action: RecommendationAction) -> bool:
    return action in _BUY_ACTIONS


def personalized_recommendation(state: ResearchState) -> dict[str, Any]:
    """
    Apply risk policy gates to the neutral recommendation.
    No LLM. Deterministic lookup of policy conditions.

    M3: assumes zero current position in all symbols (no real portfolio until M9).
    """
    symbol = state["symbol"]
    neutral = state.get("neutral_rec")

    if neutral is None:
        logger.warning("node_personalized_recommendation_no_neutral", symbol=symbol)
        return {"errors": ["personalized_recommendation_skipped: neutral_rec is None"]}

    try:
        policy_checks: list[dict[str, Any]] = []
        current_weight = 0.0  # no real portfolio until M9
        max_weight = _DEFAULT_MAX_SINGLE_STOCK_WEIGHT
        personal_action = neutral.action

        # Gate 1: position weight
        if current_weight > max_weight and _is_buy_action(personal_action):
            personal_action = RecommendationAction.HOLD
            policy_checks.append({
                "gate": "max_position_weight",
                "triggered": True,
                "reason": f"Position {current_weight:.0%} exceeds max {max_weight:.0%}",
            })
        else:
            policy_checks.append({
                "gate": "max_position_weight",
                "triggered": False,
                "current": current_weight,
                "max": max_weight,
            })

        # Gate 2: minimum confidence
        if neutral.confidence < _DEFAULT_MIN_CONFIDENCE and _is_buy_action(personal_action):
            personal_action = RecommendationAction.WATCHLIST
            policy_checks.append({
                "gate": "min_confidence",
                "triggered": True,
                "reason": (
                    f"Confidence {neutral.confidence:.2f} below threshold "
                    f"{_DEFAULT_MIN_CONFIDENCE}"
                ),
            })
        else:
            policy_checks.append({
                "gate": "min_confidence",
                "triggered": False,
                "confidence": neutral.confidence,
                "threshold": _DEFAULT_MIN_CONFIDENCE,
            })

        # Gate 3: minimum data quality
        dq = state.get("data_quality_score", 1.0)
        if dq < _DEFAULT_MIN_DATA_QUALITY and _is_buy_action(personal_action):
            personal_action = RecommendationAction.WATCHLIST
            policy_checks.append({
                "gate": "min_data_quality",
                "triggered": True,
                "reason": f"Data quality {dq:.2f} below threshold {_DEFAULT_MIN_DATA_QUALITY}",
            })
        else:
            policy_checks.append({
                "gate": "min_data_quality",
                "triggered": False,
                "data_quality": dq,
                "threshold": _DEFAULT_MIN_DATA_QUALITY,
            })

        gates_triggered = [c for c in policy_checks if c.get("triggered")]
        if gates_triggered:
            reason = f"Policy gates overrode {neutral.action.value} → {personal_action.value}. " + \
                     " ".join(c["reason"] for c in gates_triggered if "reason" in c)
        else:
            reason = (
                f"Neutral recommendation {neutral.action.value} (score {neutral.score}) "
                f"passes all risk policy gates. No current position in {symbol}."
            )

        rec = PersonalizedRecState(
            personal_action=personal_action,
            personal_reason=reason,
            policy_checks=policy_checks,
            current_position_weight=current_weight,
            max_allowed_weight=max_weight,
        )

        logger.info(
            "node_personalized_recommendation",
            symbol=symbol,
            neutral_action=neutral.action.value,
            personal_action=personal_action.value,
            gates_triggered=len(gates_triggered),
        )
        return {"personalized_rec": rec}

    except Exception as exc:
        logger.warning("node_personalized_recommendation_failed", symbol=symbol, error=str(exc))
        return {
            "errors": [f"personalized_recommendation_failed: {exc}"],
            "confidence_penalties": [0.10],
        }
