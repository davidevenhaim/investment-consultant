"""PersistResults — write recommendations to Postgres using M2 repositories."""
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from core.logging import get_logger
from db.enums import TickerRunStatus
from db.models import NeutralRecommendation as NeutralRecModel
from db.models import PersonalizedRecommendation as PersonalizedRecModel
from db.models import ResearchRunTicker
from db.repositories import StrategyVersionRepository
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.state import ResearchState

logger = get_logger(__name__)


def make_persist_results(session: AsyncSession) -> Callable[[ResearchState], Any]:
    """
    Factory that binds the DB session into the node closure.
    Called once per research run; the returned node is reused for each ticker.
    The ticker's DB record ID is read from state["run_ticker_id"].
    """

    async def persist_results(state: ResearchState) -> dict[str, Any]:
        symbol = state["symbol"]
        ticker_db_id = uuid.UUID(state["run_ticker_id"])
        run_id = uuid.UUID(state["run_id"])

        try:
            neutral = state.get("neutral_rec")
            personalized = state.get("personalized_rec")

            # Resolve strategy version UUID from version string
            sv_repo = StrategyVersionRepository(session)
            sv = await sv_repo.get_by_version(state["strategy_version"])
            sv_id = sv.id if sv else None

            # Derive latest close for price_at_recommendation
            signals = state.get("technical_signals") or {}
            price_at_rec: float | None = signals.get("latest_close")

            # Persist neutral recommendation
            neutral_rec_id: uuid.UUID | None = None
            if neutral is not None:
                nr = NeutralRecModel(
                    research_run_id=run_id,
                    research_run_ticker_id=ticker_db_id,
                    symbol=symbol,
                    action=neutral.action.value,
                    score=neutral.score,
                    confidence=neutral.confidence,
                    score_breakdown_json=neutral.score_breakdown.model_dump(),
                    what_changed_json=[],
                    main_reasons_json=neutral.main_reasons,
                    main_risks_json=neutral.main_risks,
                    missing_details_json=neutral.missing_details,
                    final_reason=neutral.final_reason,
                    strategy_version_id=sv_id,
                    as_of_time=state["as_of_time"],
                    price_at_recommendation=price_at_rec,
                    data_quality_score=neutral.data_quality_score,
                )
                session.add(nr)
                await session.flush()
                neutral_rec_id = nr.id
                logger.info(
                    "persist_neutral_rec",
                    symbol=symbol,
                    action=neutral.action.value,
                    score=neutral.score,
                )

            # Persist personalized recommendation
            if personalized is not None and neutral_rec_id is not None:
                pr = PersonalizedRecModel(
                    neutral_recommendation_id=neutral_rec_id,
                    symbol=symbol,
                    personal_action=personalized.personal_action.value,
                    position_sizing_json={},
                    policy_checks_json=personalized.policy_checks,
                    current_position_weight=personalized.current_position_weight,
                    max_allowed_weight=personalized.max_allowed_weight,
                    personal_reason=personalized.personal_reason,
                )
                session.add(pr)
                await session.flush()
                logger.info(
                    "persist_personalized_rec",
                    symbol=symbol,
                    action=personalized.personal_action.value,
                )

            # Update ticker status to COMPLETED
            ticker = await session.get(ResearchRunTicker, ticker_db_id)
            if ticker is not None:
                ticker.status = TickerRunStatus.COMPLETED.value
                ticker.finished_at = datetime.now(UTC)
                await session.flush()

            return {}

        except Exception as exc:
            logger.error("node_persist_results_failed", symbol=symbol, error=str(exc))
            # Per PRINCIPLES.md #3: log, degrade, never crash the run.
            try:
                ticker = await session.get(ResearchRunTicker, ticker_db_id)
                if ticker is not None:
                    ticker.status = TickerRunStatus.FAILED.value
                    ticker.error_message = str(exc)[:500]
                    ticker.finished_at = datetime.now(UTC)
                    await session.flush()
            except Exception as inner_exc:
                logger.warning("persist_results_cleanup_failed", error=str(inner_exc))
            return {"errors": [f"persist_results_failed: {exc}"]}

    return persist_results
