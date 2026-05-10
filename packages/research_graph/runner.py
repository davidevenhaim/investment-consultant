"""Runner — orchestrates the graph for a full research run (all tickers)."""

from datetime import UTC, datetime
from typing import Any

from ai.interfaces import LLMClient
from core.logging import get_logger
from db.enums import TickerRunStatus
from db.models import ResearchRun, ResearchRunTicker
from fundamentals.interfaces import FundamentalsProvider
from market_data.interfaces import MarketDataProvider
from memory.interfaces import MemoryStore
from news.interfaces import NewsProvider
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.graph import build_graph_for_session
from research_graph.state import ResearchState

logger = get_logger(__name__)

# Default scoring config used if strategy version is missing from DB
_DEFAULT_SCORING_CONFIG: dict[str, Any] = {
    "version": "v0.1.0",
    "score_weights": {
        "technical": 20,
        "risk": 15,
        "fundamental": 20,
        "valuation": 15,
        "news": 15,
        "portfolio_fit": 15,
    },
    "stub_scores": {"news": 5, "portfolio_fit": 7},
    "action_thresholds": {
        "strong_buy": 85,
        "buy_candidate": 70,
        "hold": 50,
        "reduce": 35,
    },
    "data_quality_thresholds": {
        "minimum_to_buy": 0.75,
        "minimum_to_recommend": 0.50,
    },
    "confidence_thresholds": {"minimum_to_buy": 0.65},
    "risk_policy": {
        "max_single_stock_weight": 0.15,
        "min_confidence_to_buy": 0.65,
    },
    "action_caps": {
        "missing_news": "BUY_CANDIDATE",
        "missing_portfolio_context": "BUY_CANDIDATE",
        "low_fundamentals_quality": "WATCHLIST",
        "low_market_data_quality": "WATCHLIST",
    },
}


def make_initial_state(
    run: ResearchRun,
    ticker: ResearchRunTicker,
    strategy_version: str,
    strategy_config: dict[str, Any] | None = None,
) -> ResearchState:
    """Build the initial state for one ticker in a research run."""
    return ResearchState(
        run_id=str(run.id),
        run_ticker_id=str(ticker.id),
        symbol=ticker.symbol,
        as_of_time=datetime.now(UTC),
        strategy_version=strategy_version,
        prompt_version="v0.1.0",
        strategy_config=strategy_config or _DEFAULT_SCORING_CONFIG,
        llm_analysis=None,
        llm_warnings=[],
        llm_confidence_penalty=0.0,
        memory_context=None,
        memory_count=0,
        memory_summary=None,
        previous_thesis=None,
        last_recommendation=None,
        past_mistakes=[],
        ohlcv=None,
        technical_signals=None,
        news_items=[],
        news_score_result=None,
        news_analysis=None,
        broker_account_id=None,
        portfolio_context=None,
        portfolio_snapshot_id=None,
        current_position_weight=0.0,
        current_position_value=None,
        current_quantity=0.0,
        cash_available=None,
        target_position_weight=None,
        suggested_trade_json=None,
        thesis_comparison=None,
        missing_details=None,
        bull_bear_case=None,
        score_breakdown=None,
        neutral_rec=None,
        portfolio_snapshot=None,
        personalized_rec=None,
        fundamentals_snapshot=None,
        fundamentals_data_quality=0.0,
        analysis_completeness=0.0,
        completed_components=[],
        missing_components=[],
        symbol_trading_stats=None,
        trading_profile=None,
        behavioral_flags=[],
        ibkr_sync_available=False,
        errors=[],
        data_quality_score=1.0,
        confidence_penalties=[],
    )


async def run_research_for_run(
    run: ResearchRun,
    tickers: list[ResearchRunTicker],
    session: AsyncSession,
    strategy_version: str,
    market_provider: MarketDataProvider | None = None,
    fundamentals_provider: FundamentalsProvider | None = None,
    memory_store: MemoryStore | None = None,
    llm_client: LLMClient | None = None,
    news_provider: NewsProvider | None = None,
) -> dict[str, Any]:
    """
    Run the research graph for every ticker in the run.
    Updates each ticker's status in DB. Returns a summary dict.
    Providers may be injected for testing; default to yfinance implementations.
    """
    # Load strategy config once for the whole run
    from db.repositories import StrategyVersionRepository

    sv_repo = StrategyVersionRepository(session)
    sv = await sv_repo.get_by_version(strategy_version)
    strategy_config = dict(sv.scoring_config_json) if sv and sv.scoring_config_json else {}
    if not strategy_config:
        strategy_config = _DEFAULT_SCORING_CONFIG

    graph = build_graph_for_session(
        session, market_provider, fundamentals_provider, memory_store, llm_client, news_provider
    )
    results: dict[str, Any] = {"symbols_completed": [], "symbols_failed": [], "errors": []}

    for ticker in tickers:
        symbol = ticker.symbol
        ticker.status = TickerRunStatus.RUNNING.value
        ticker.started_at = datetime.now(UTC)
        await session.flush()

        logger.info("research_ticker_start", symbol=symbol, run_id=str(run.id))

        try:
            initial_state = make_initial_state(run, ticker, strategy_version, strategy_config)
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
                completeness=final_state.get("analysis_completeness"),
            )

        except Exception as exc:
            logger.error("research_ticker_failed", symbol=symbol, error=str(exc))
            results["symbols_failed"].append(symbol)
            results["errors"].append(f"{symbol}: {exc}")
            ticker.status = TickerRunStatus.FAILED.value
            ticker.error_message = str(exc)[:500]
            ticker.finished_at = datetime.now(UTC)
            await session.flush()

    return results
