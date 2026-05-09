"""PersonalizedRecommendation — apply risk policy engine to produce portfolio-aware action."""

from typing import Any

from core.logging import get_logger
from decision_engine.policy import apply_policy

from research_graph.state import PersonalizedRecState, ResearchState

logger = get_logger(__name__)


def personalized_recommendation(state: ResearchState) -> dict[str, Any]:
    """
    Apply deterministic risk policy gates to the neutral recommendation.
    No LLM. Uses policy engine from decision_engine.policy.
    M9 replaces zero position weight with real IBKR portfolio data.
    """
    symbol = state["symbol"]
    neutral = state.get("neutral_rec")

    if neutral is None:
        logger.warning("node_personalized_recommendation_no_neutral", symbol=symbol)
        return {"errors": ["personalized_recommendation_skipped: neutral_rec is None"]}

    try:
        strategy_config = state.get("strategy_config") or {}
        fdq = state.get("fundamentals_data_quality") or 0.0
        market_dq = state.get("data_quality_score") or 1.0
        missing = state.get("missing_components") or []

        result = apply_policy(
            action=neutral.action,
            confidence=neutral.confidence,
            data_quality_score=market_dq,
            fundamentals_data_quality=fdq,
            completed_components=state.get("completed_components") or [],
            missing_components=missing,
            has_position=False,  # M9: replaced with real IBKR position
            current_position_weight=0.0,
            strategy_config=strategy_config,
        )

        gates_triggered = [c for c in result.policy_checks if c.get("triggered")]
        if gates_triggered:
            reason = (
                f"Policy gates overrode {neutral.action.value} → "
                f"{result.final_action.value}. "
                + " ".join(c.get("reason", "") for c in gates_triggered if "reason" in c)
            )
        else:
            reason = (
                f"Neutral recommendation {neutral.action.value} (score {neutral.score}) "
                f"passes all policy gates. No current position in {symbol}."
            )
        if result.reasons:
            reason += " " + " ".join(result.reasons)

        rec = PersonalizedRecState(
            personal_action=result.final_action,
            personal_reason=reason.strip(),
            policy_checks=result.policy_checks,
            current_position_weight=0.0,
            max_allowed_weight=strategy_config.get("risk_policy", {}).get(
                "max_single_stock_weight", 0.15
            ),
        )

        logger.info(
            "node_personalized_recommendation",
            symbol=symbol,
            neutral_action=neutral.action.value,
            personal_action=result.final_action.value,
            cap_applied=result.action_cap_applied,
            gates_triggered=len(gates_triggered),
        )
        return {"personalized_rec": rec}

    except Exception as exc:
        logger.warning("node_personalized_recommendation_failed", symbol=symbol, error=str(exc))
        return {
            "errors": [f"personalized_recommendation_failed: {exc}"],
            "confidence_penalties": [0.10],
        }
