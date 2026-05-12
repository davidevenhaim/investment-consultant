"""LoadPortfolioContext — load real portfolio data and update neutral rec with portfolio fit."""

import uuid
from collections.abc import Callable
from typing import Any

from core.logging import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.state import NeutralRecState, ResearchState, ScoreBreakdown

logger = get_logger(__name__)

_DEFAULT_MAX_WEIGHT = 0.15


def make_load_portfolio_context(
    session: AsyncSession,
) -> Callable[[ResearchState], Any]:
    """Factory: bind DB session into node closure."""

    async def load_portfolio_context(state: ResearchState) -> dict[str, Any]:
        symbol = state["symbol"]
        try:
            from portfolio.service import get_portfolio_context_for_symbol

            raw_user_id = state.get("user_id")
            user_id = uuid.UUID(raw_user_id) if raw_user_id is not None else None
            ctx = await get_portfolio_context_for_symbol(session, symbol, user_id=user_id)

            # Debug: always log what was found before writing to state
            if ctx is None:
                logger.info(
                    "load_portfolio_context_no_portfolio",
                    symbol=symbol,
                    reason="no default portfolio account found",
                )
                # Still load trading stats even without a portfolio account
                return await _load_trade_stats_only(state, session, symbol)

            pos = ctx.position
            logger.debug(
                "load_portfolio_context_found",
                symbol=symbol,
                has_position=pos is not None,
                position_quantity=pos.quantity if pos else 0.0,
                position_weight=pos.weight if pos else 0.0,
                position_market_value=pos.market_value if pos else None,
                total_equity=ctx.total_equity,
                cash_balance=ctx.cash_balance,
                num_positions=ctx.number_of_positions,
                snapshot_id=str(ctx.snapshot_id) if ctx.snapshot_id else None,
                concentration=ctx.concentration_score,
            )

            current_weight = pos.weight if pos else 0.0
            current_quantity = pos.quantity if pos else 0.0
            current_value = pos.market_value if pos else None
            has_position = current_quantity > 0

            strategy_config = state.get("strategy_config") or {}
            max_weight = float(
                ctx.max_single_stock_weight
                or strategy_config.get("risk_policy", {}).get(
                    "max_single_stock_weight", _DEFAULT_MAX_WEIGHT
                )
            )

            neutral = state.get("neutral_rec")
            neutral_action = neutral.action.value if neutral else "HOLD"

            from portfolio.risk import portfolio_fit_score

            pfit = portfolio_fit_score(
                current_weight=current_weight,
                max_weight=max_weight,
                cash_balance=ctx.cash_balance,
                total_equity=ctx.total_equity,
                concentration=ctx.concentration_score,
                has_position=has_position,
                neutral_action=neutral_action,
            )

            # Update neutral_rec in state with real portfolio fit score
            updates: dict[str, Any] = {}
            if neutral is not None:
                from research_graph.nodes.neutral_recommendation import score_to_action

                old_pfit = neutral.score_breakdown.portfolio_fit_score
                delta = pfit - old_pfit
                new_total = max(0, min(100, neutral.score + round(delta)))
                new_action = score_to_action(float(new_total), config=strategy_config)

                # Update completeness metadata inside score_breakdown
                old_bd = neutral.score_breakdown
                new_completed = list(old_bd.completed_components)
                new_missing = list(old_bd.missing_components)
                if "portfolio_context" in new_missing:
                    new_missing.remove("portfolio_context")
                if "portfolio_context" not in new_completed:
                    new_completed.append("portfolio_context")
                new_quality = dict(old_bd.component_quality_scores)
                new_quality["portfolio_context"] = 1.0
                total_items = len(new_completed) + len(new_missing)
                new_completeness = (
                    round(len(new_completed) / total_items, 3) if total_items > 0 else 0.0
                )

                new_breakdown = ScoreBreakdown(
                    **{
                        **old_bd.model_dump(),
                        "portfolio_fit_score": round(pfit, 2),
                        "total_score": float(new_total),
                        "completed_components": new_completed,
                        "missing_components": new_missing,
                        "component_quality_scores": new_quality,
                        "analysis_completeness_score": new_completeness,
                    }
                )
                # Remove portfolio-pending entries from missing_details and main_risks
                new_missing_details = [
                    m for m in neutral.missing_details if "portfolio" not in m.lower()
                ]
                new_main_risks = [
                    r for r in neutral.main_risks
                    if "portfolio context pending" not in r.lower()
                ]
                new_neutral = NeutralRecState(
                    **{
                        **neutral.model_dump(),
                        "score": new_total,
                        "action": new_action,
                        "score_breakdown": new_breakdown,
                        "missing_details": new_missing_details,
                        "main_risks": new_main_risks,
                        "final_reason": _update_final_reason(
                            neutral.final_reason, pfit, new_total, new_action.value
                        ),
                    }
                )
                updates["neutral_rec"] = new_neutral
                updates["score_breakdown"] = new_breakdown

            # Sync state-level completeness with what was written into score_breakdown
            # (when neutral is None, fall back to mutating state lists directly)
            if neutral is not None:
                completed = list(new_completed)
                missing = list(new_missing)
            else:
                completed = list(state.get("completed_components") or [])
                missing = list(state.get("missing_components") or [])
                if "portfolio_context" in missing:
                    missing.remove("portfolio_context")
                if "portfolio_context" not in completed:
                    completed.append("portfolio_context")

            portfolio_snapshot_id = str(ctx.snapshot_id) if ctx.snapshot_id else None
            ctx_dict = ctx.as_dict()

            # Load trade history stats for this symbol (M9.5/M9.6)
            import contextlib
            import uuid as _uuid

            raw_ba_id = state.get("broker_account_id")
            ba_uuid: _uuid.UUID | None = None
            if raw_ba_id:
                with contextlib.suppress(ValueError):
                    ba_uuid = _uuid.UUID(raw_ba_id)

            symbol_trading_stats: dict[str, Any] = {}
            behavioral_flags: list[str] = []
            try:
                from portfolio.trade_history_service import (
                    get_latest_profile,
                    get_symbol_trading_stats,
                )

                symbol_trading_stats = await get_symbol_trading_stats(
                    session, symbol, broker_account_id=ba_uuid
                )
                latest_profile = await get_latest_profile(session, broker_account_id=ba_uuid)
                if latest_profile:
                    behavioral_flags = list(latest_profile.behavioral_flags_json or [])
            except Exception as trade_exc:
                logger.debug(
                    "load_portfolio_context_trade_stats_failed",
                    symbol=symbol,
                    error=str(trade_exc),
                )

            logger.info(
                "load_portfolio_context_ok",
                symbol=symbol,
                current_weight=current_weight,
                portfolio_fit_score=pfit,
                has_position=has_position,
                snapshot_id=portfolio_snapshot_id,
                has_trade_stats=bool(symbol_trading_stats),
            )
            # analysis_completeness in state mirrors score_breakdown
            state_completeness = (
                new_completeness
                if neutral is not None
                else (
                    len(completed) / (len(completed) + len(missing))
                    if (len(completed) + len(missing)) > 0 else 0.0
                )
            )

            return {
                **updates,
                "portfolio_context": ctx_dict,
                "portfolio_snapshot_id": portfolio_snapshot_id,
                "current_position_weight": current_weight,
                "current_position_value": current_value,
                "current_quantity": current_quantity,
                "cash_available": ctx.cash_balance,
                "completed_components": completed,
                "missing_components": missing,
                "analysis_completeness": round(state_completeness, 3),
                "symbol_trading_stats": symbol_trading_stats or None,
                "behavioral_flags": behavioral_flags,
            }

        except Exception as exc:
            logger.warning("load_portfolio_context_failed", symbol=symbol, error=str(exc))
            return _safe_defaults()

    return load_portfolio_context


def _safe_defaults() -> dict[str, Any]:
    return {
        "portfolio_context": None,
        "portfolio_snapshot_id": None,
        "current_position_weight": 0.0,
        "current_position_value": None,
        "current_quantity": 0.0,
        "cash_available": None,
        "symbol_trading_stats": None,
        "behavioral_flags": [],
    }


async def _load_trade_stats_only(
    state: "ResearchState",
    session: AsyncSession,
    symbol: str,
) -> dict[str, Any]:
    """Return safe defaults + trading stats when no portfolio account exists."""
    import contextlib
    import uuid as _uuid

    raw_ba_id = state.get("broker_account_id")
    ba_uuid: _uuid.UUID | None = None
    if raw_ba_id:
        with contextlib.suppress(ValueError):
            ba_uuid = _uuid.UUID(raw_ba_id)

    symbol_trading_stats: dict[str, Any] = {}
    behavioral_flags: list[str] = []
    try:
        from portfolio.trade_history_service import (
            get_latest_profile,
            get_symbol_trading_stats,
        )

        symbol_trading_stats = await get_symbol_trading_stats(
            session, symbol, broker_account_id=ba_uuid
        )
        latest_profile = await get_latest_profile(session, broker_account_id=ba_uuid)
        if latest_profile:
            behavioral_flags = list(latest_profile.behavioral_flags_json or [])
    except Exception as trade_exc:
        logger.debug(
            "load_portfolio_context_trade_stats_failed",
            symbol=symbol,
            error=str(trade_exc),
        )

    return {
        **_safe_defaults(),
        "symbol_trading_stats": symbol_trading_stats or None,
        "behavioral_flags": behavioral_flags,
    }


def _update_final_reason(
    original: str,
    pfit: float,
    new_total: int,
    new_action: str,
) -> str:
    """Patch final_reason to reflect updated total score, action, and real portfolio fit."""
    import re

    reason = original

    # Update leading score/action stamp (Score X/100 (ACTION))
    reason = re.sub(
        r"Score \d+/100 \([^)]+\)",
        f"Score {new_total}/100 ({new_action})",
        reason,
    )

    # Replace portfolio stub with real fit score
    if "Portfolio stub:" in reason:
        reason = re.sub(
            r"Portfolio stub: \d+/15",
            f"Portfolio fit (real): {pfit:.0f}/15",
            reason,
        )
    elif "Portfolio fit" not in reason:
        reason += f" Portfolio fit (real): {pfit:.0f}/15."

    return reason
