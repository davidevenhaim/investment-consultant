"""Runner — orchestrates the graph for a full research run (all tickers)."""
from datetime import UTC, datetime
from typing import Any

from core.logging import get_logger
from db.enums import TickerRunStatus
from db.models import ResearchRun, ResearchRunTicker
from market_data.interfaces import MarketDataProvider
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.graph import build_graph_for_session
from research_graph.state import ResearchState

logger = get_logger(__name__)


def make_initial_state(
    run: ResearchRun,
    ticker: ResearchRunTicker,
    strategy_version: str,
) -> ResearchState:
    """Build the initial state for one ticker in a research run."""
    return ResearchState(
        run_id=str(run.id),
        run_ticker_id=str(ticker.id),
        symbol=ticker.symbol,
        as_of_time=datetime.now(UTC),
        strategy_version=strategy_version,
        prompt_version="v0.1.0",
        previous_thesis=None,
        last_recommendation=None,
        past_mistakes=[],
        ohlcv=None,
        technical_signals=None,
        news_items=[],
        news_analysis=None,
        thesis_comparison=None,
        missing_details=None,
        bull_bear_case=None,
        score_breakdown=None,
        neutral_rec=None,
        portfolio_snapshot=None,
        personalized_rec=None,
        errors=[],
        data_quality_score=1.0,
        confidence_penalties=[],
    )


async def run_research_for_run(
    run: ResearchRun,
    tickers: list[ResearchRunTicker],
    session: AsyncSession,
    strategy_version: str,
    provider: MarketDataProvider | None = None,
) -> dict[str, Any]:
    """
    Run the research graph for every ticker in the run.
    Updates each ticker's status in DB. Returns a summary dict.
    `provider` may be injected for testing; defaults to YFinanceProvider.
    """
    graph = build_graph_for_session(session, provider)

    results: dict[str, Any] = {"symbols_completed": [], "symbols_failed": [], "errors": []}

    for ticker in tickers:
        symbol = ticker.symbol
        # Mark ticker as running
        ticker.status = TickerRunStatus.RUNNING.value
        ticker.started_at = datetime.now(UTC)
        await session.flush()

        logger.info("research_ticker_start", symbol=symbol, run_id=str(run.id))

        try:
            initial_state = make_initial_state(run, ticker, strategy_version)
            final_state: ResearchState = await graph.ainvoke(initial_state)

            node_errors: list[str] = final_state.get("errors", [])
            if node_errors:
                results["errors"].extend(node_errors)
                logger.warning("research_ticker_node_errors", symbol=symbol, errors=node_errors)

            results["symbols_completed"].append(symbol)
            neutral = final_state.get("neutral_rec")
            logger.info(
                "research_ticker_done",
                symbol=symbol,
                score=neutral.score if neutral is not None else None,
                action=neutral.action.value if neutral is not None else None,
            )

        except Exception as exc:
            logger.error("research_ticker_failed", symbol=symbol, error=str(exc))
            results["symbols_failed"].append(symbol)
            results["errors"].append(f"{symbol}: {exc}")
            # Degrade gracefully — mark ticker failed, continue with next
            ticker.status = TickerRunStatus.FAILED.value
            ticker.error_message = str(exc)[:500]
            ticker.finished_at = datetime.now(UTC)
            await session.flush()

    return results
