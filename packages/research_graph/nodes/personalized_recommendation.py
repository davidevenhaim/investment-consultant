"""PersonalizedRecommendation — apply risk policy + portfolio sizing to produce personal action."""

from typing import Any

from core.logging import get_logger
from db.enums import RecommendationAction
from decision_engine.policy import apply_policy
from portfolio.risk import build_trade_suggestion, recommended_position_size

from research_graph.state import PersonalizedRecState, ResearchState

logger = get_logger(__name__)


def personalized_recommendation(state: ResearchState) -> dict[str, Any]:
    """
    Apply deterministic risk policy gates + portfolio-aware sizing.
    No LLM. Reads real portfolio context from state (populated by load_portfolio_context).
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

        # Portfolio context (populated by load_portfolio_context; safe defaults if absent)
        port_ctx = state.get("portfolio_context") or {}
        current_weight = state.get("current_position_weight") or 0.0
        current_quantity = state.get("current_quantity") or 0.0
        has_position = current_quantity > 0

        risk_policy = strategy_config.get("risk_policy", {})
        max_weight = float(
            port_ctx.get("max_single_stock_weight")
            or risk_policy.get("max_single_stock_weight", 0.15)
        )
        risk_level = str(port_ctx.get("risk_level", "MEDIUM"))
        total_equity = float(port_ctx.get("total_equity", 0.0))
        portfolio_snapshot_id = state.get("portfolio_snapshot_id")

        # Apply policy gates (existing logic)
        result = apply_policy(
            action=neutral.action,
            confidence=neutral.confidence,
            data_quality_score=market_dq,
            fundamentals_data_quality=fdq,
            completed_components=state.get("completed_components") or [],
            missing_components=missing,
            has_position=has_position,
            current_position_weight=current_weight,
            strategy_config=strategy_config,
        )

        personal_action = result.final_action
        extra_reasons: list[str] = list(result.reasons)

        # M9 action override rules
        if personal_action == RecommendationAction.HOLD and not has_position:
            personal_action = RecommendationAction.WATCHLIST
            extra_reasons.append(f"HOLD with no {symbol} position → WATCHLIST.")

        if personal_action == RecommendationAction.REDUCE and not has_position:
            personal_action = RecommendationAction.NO_ACTION
            extra_reasons.append(f"REDUCE with no {symbol} position → NO_ACTION.")

        # Position sizing
        target_weight = recommended_position_size(
            risk_level=risk_level,
            score=neutral.score,
            confidence=neutral.confidence,
            max_single_stock_weight=max_weight,
        )

        suggested_trade = build_trade_suggestion(
            personal_action=personal_action,
            current_weight=current_weight,
            target_weight=target_weight,
            max_weight=max_weight,
            total_equity=total_equity,
        )

        # Build reason string
        gates_triggered = [c for c in result.policy_checks if c.get("triggered")]
        if gates_triggered:
            reason = (
                f"Policy gates overrode {neutral.action.value} → {personal_action.value}. "
                + " ".join(c.get("reason", "") for c in gates_triggered if "reason" in c)
            )
        elif extra_reasons:
            reason = " ".join(extra_reasons)
        else:
            pos_str = f"{current_weight:.0%}" if has_position else "no position"
            reason = (
                f"Neutral {neutral.action.value} (score {neutral.score}) passes all "
                f"policy gates. {symbol} position: {pos_str}."
            )

        trade_type = suggested_trade.get("trade_type", "NONE")
        if trade_type != "NONE" and target_weight > 0:
            reason += (
                f" Suggested {trade_type}: target {target_weight:.0%} "
                f"(current {current_weight:.0%})."
            )

        rec = PersonalizedRecState(
            personal_action=personal_action,
            personal_reason=reason.strip(),
            policy_checks=result.policy_checks,
            current_position_weight=current_weight,
            max_allowed_weight=max_weight,
            suggested_trade_json=suggested_trade,
            portfolio_snapshot_id=portfolio_snapshot_id,
        )

        logger.info(
            "node_personalized_recommendation",
            symbol=symbol,
            neutral_action=neutral.action.value,
            personal_action=personal_action.value,
            cap_applied=result.action_cap_applied,
            gates_triggered=len(gates_triggered),
            has_position=has_position,
            current_weight=current_weight,
            target_weight=target_weight,
            trade_type=trade_type,
        )
        return {
            "personalized_rec": rec,
            "target_position_weight": target_weight,
            "suggested_trade_json": suggested_trade,
        }

    except Exception as exc:
        logger.warning("node_personalized_recommendation_failed", symbol=symbol, error=str(exc))
        return {
            "errors": [f"personalized_recommendation_failed: {exc}"],
            "confidence_penalties": [0.10],
        }
