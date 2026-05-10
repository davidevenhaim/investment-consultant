"""PersistResults — write recommendations to Postgres, then index to ChromaDB."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from core.logging import get_logger
from db.enums import EvidenceType, TickerRunStatus
from db.models import MemoryIndexEvent, RecommendationEvidence, ResearchRunTicker
from db.models import NeutralRecommendation as NeutralRecModel
from db.models import PersonalizedRecommendation as PersonalizedRecModel
from db.repositories import StrategyVersionRepository
from memory.collections import RECOMMENDATION_REPORTS
from memory.interfaces import MemoryStore
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.state import ResearchState

logger = get_logger(__name__)


def make_persist_results(
    session: AsyncSession,
    memory_store: MemoryStore | None = None,
) -> Callable[[ResearchState], Any]:
    """
    Factory that binds the DB session and optional MemoryStore into the node closure.
    Postgres write is authoritative; ChromaDB indexing is best-effort (never raises).
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
            personalized_rec_id: uuid.UUID | None = None
            if personalized is not None and neutral_rec_id is not None:
                import contextlib  # noqa: PLC0415
                snap_id: uuid.UUID | None = None
                if personalized.portfolio_snapshot_id:
                    with contextlib.suppress(ValueError):
                        snap_id = uuid.UUID(personalized.portfolio_snapshot_id)
                symbol_trading_stats = state.get("symbol_trading_stats") or {}
                pr = PersonalizedRecModel(
                    neutral_recommendation_id=neutral_rec_id,
                    symbol=symbol,
                    personal_action=personalized.personal_action.value,
                    position_sizing_json=personalized.suggested_trade_json or {},
                    policy_checks_json=personalized.policy_checks,
                    current_position_weight=personalized.current_position_weight,
                    max_allowed_weight=personalized.max_allowed_weight,
                    personal_reason=personalized.personal_reason,
                    portfolio_snapshot_id=snap_id,
                    symbol_trading_stats_json=symbol_trading_stats,
                )
                session.add(pr)
                await session.flush()
                personalized_rec_id = pr.id
                logger.info(
                    "persist_personalized_rec",
                    symbol=symbol,
                    action=personalized.personal_action.value,
                )

            # Persist LLM evidence row (when LLM enabled)
            llm: Any = state.get("llm_analysis")
            if llm is not None and llm.llm_enabled and neutral_rec_id is not None:
                from core.config import get_settings as _gs
                _s = _gs()
                thesis_align = llm.thesis.previous_thesis_alignment
                ev = RecommendationEvidence(
                    recommendation_id=neutral_rec_id,
                    recommendation_type="NEUTRAL",
                    evidence_type=EvidenceType.LLM_ANALYSIS.value,
                    source=f"claude/{_s.llm_model}",
                    summary=(
                        f"Combined LLM analysis: thesis_alignment={thesis_align}, "
                        f"penalty={llm.total_confidence_penalty:.3f}, "
                        f"quality={llm.analysis_quality_score:.2f}"
                    ),
                    payload_json={
                        **llm.model_dump(),
                        "prompt_version_id": state.get("llm_prompt_version_id"),
                    },
                )
                session.add(ev)
                await session.flush()

            # Persist news evidence rows (when news data available)
            news_score_result: Any = state.get("news_score_result")
            if news_score_result is not None and neutral_rec_id is not None:
                # One NEWS_ANALYSIS row summarising the scoring result
                news_ev = RecommendationEvidence(
                    recommendation_id=neutral_rec_id,
                    recommendation_type="NEUTRAL",
                    evidence_type=EvidenceType.NEWS_ANALYSIS.value,
                    source=f"news/{news_score_result.no_data and 'no_data' or 'scored'}",
                    summary=(
                        f"News score: {news_score_result.score:.1f}/15 — "
                        f"{news_score_result.article_count} articles "
                        f"({news_score_result.positive_count}+/"
                        f"{news_score_result.negative_count}-). "
                        f"{news_score_result.reason}"
                    ),
                    payload_json=news_score_result.model_dump(
                        exclude={"top_articles"}
                    ),
                )
                session.add(news_ev)

                # Up to 3 individual NEWS_ITEM evidence rows for top articles
                top_articles = (
                    news_score_result.top_articles[:3]
                    if news_score_result.top_articles
                    else []
                )
                for art in top_articles:
                    art_ev = RecommendationEvidence(
                        recommendation_id=neutral_rec_id,
                        recommendation_type="NEUTRAL",
                        evidence_type=EvidenceType.NEWS_ITEM.value,
                        source=art.source_name,
                        source_id=art.provider_article_id,
                        summary=art.title[:500],
                        url=art.url,
                        published_at=art.published_at,
                        payload_json={
                            "sentiment_score": art.sentiment_score,
                            "relevance_score": art.relevance_score,
                            "importance_score": art.importance_score,
                        },
                    )
                    session.add(art_ev)

                await session.flush()

            # Persist PORTFOLIO_CONTEXT evidence row (when portfolio context exists)
            port_ctx = state.get("portfolio_context")
            if port_ctx is not None and neutral_rec_id is not None:
                current_w = state.get("current_position_weight") or 0.0
                target_w = state.get("target_position_weight")
                cash_av = state.get("cash_available")
                port_ev = RecommendationEvidence(
                    recommendation_id=neutral_rec_id,
                    recommendation_type="NEUTRAL",
                    evidence_type=EvidenceType.PORTFOLIO_CONTEXT.value,
                    source="manual_portfolio",
                    summary=(
                        f"Portfolio context: current weight {current_w:.1%}, "
                        f"target weight {target_w:.1%}" if target_w is not None
                        else f"Portfolio context: current weight {current_w:.1%}. "
                        + (f"Cash available ${cash_av:,.0f}." if cash_av else "")
                    ),
                    payload_json={
                        **{k: v for k, v in port_ctx.items() if k != "position"},
                        "current_weight": current_w,
                        "target_weight": target_w,
                        "suggested_trade": state.get("suggested_trade_json"),
                    },
                )
                session.add(port_ev)
                await session.flush()

            # Update ticker status to COMPLETED
            ticker = await session.get(ResearchRunTicker, ticker_db_id)
            if ticker is not None:
                ticker.status = TickerRunStatus.COMPLETED.value
                ticker.finished_at = datetime.now(UTC)
                await session.flush()

        except Exception as exc:
            logger.error("node_persist_results_failed", symbol=symbol, error=str(exc))
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

        # ChromaDB indexing — best-effort, never crashes the run
        await _index_to_chroma(
            session=session,
            store=memory_store,
            symbol=symbol,
            run_id=run_id,
            neutral_rec_id=neutral_rec_id,
            personalized_rec_id=personalized_rec_id,
            state=state,
            price_at_rec=price_at_rec,
            sv_id=sv_id,
        )

        return {}

    return persist_results


async def _index_to_chroma(
    session: AsyncSession,
    store: MemoryStore | None,
    symbol: str,
    run_id: uuid.UUID,
    neutral_rec_id: uuid.UUID | None,
    personalized_rec_id: uuid.UUID | None,
    state: ResearchState,
    price_at_rec: float | None,
    sv_id: uuid.UUID | None,
) -> None:
    from memory.service import index_recommendation_report

    neutral = state.get("neutral_rec")
    personalized = state.get("personalized_rec")

    llm_analysis = state.get("llm_analysis")
    success = await index_recommendation_report(
        symbol=symbol,
        neutral_rec=neutral,
        personalized_rec=personalized,
        run_id=str(run_id),
        neutral_rec_id=str(neutral_rec_id) if neutral_rec_id else None,
        personalized_rec_id=str(personalized_rec_id) if personalized_rec_id else None,
        price_at_recommendation=price_at_rec,
        strategy_version_id=str(sv_id) if sv_id else None,
        llm_analysis=llm_analysis,
        store=store,
    )

    # Always record audit event in Postgres
    chroma_doc_id = f"rec_{run_id}_{symbol}" if neutral_rec_id else None
    event = MemoryIndexEvent(
        entity_type="neutral_recommendation",
        entity_id=neutral_rec_id,
        symbol=symbol,
        collection_name=RECOMMENDATION_REPORTS,
        chroma_document_id=chroma_doc_id,
        status="INDEXED" if success else "FAILED",
        error_message=None if success else "Chroma indexing failed; see memory service logs",
    )
    try:
        session.add(event)
        await session.flush()
    except Exception as exc:
        logger.warning("memory_audit_event_failed", symbol=symbol, error=str(exc))
