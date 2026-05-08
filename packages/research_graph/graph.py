"""Build the M4 research graph.

Session-in-closure pattern: nodes needing DB get it bound via factory functions.
"""
from typing import Any

from langgraph.graph import END, StateGraph
from market_data.interfaces import MarketDataProvider
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.nodes.compute_signals import make_compute_signals
from research_graph.nodes.fetch_market_data import make_fetch_market_data
from research_graph.nodes.load_ticker_context import load_ticker_context
from research_graph.nodes.neutral_recommendation import neutral_recommendation
from research_graph.nodes.persist_results import make_persist_results
from research_graph.nodes.personalized_recommendation import personalized_recommendation
from research_graph.nodes.retrieve_memory import retrieve_memory
from research_graph.state import ResearchState


def build_graph_for_session(
    session: AsyncSession,
    provider: MarketDataProvider | None = None,
) -> Any:
    """
    Compile research graph with DB session bound into all DB-dependent nodes.
    `provider` may be injected for testing; defaults to YFinanceProvider.

    Graph order (CLAUDE.md M4):
    LoadTickerContext → RetrieveMemory → FetchMarketData → ComputeSignals
    → NeutralRecommendation → PersonalizedRecommendation → PersistResults
    """
    fetch_fn: Any = make_fetch_market_data(session, provider)
    signals_fn: Any = make_compute_signals(session, provider)
    persist_fn: Any = make_persist_results(session)

    builder: StateGraph = StateGraph(ResearchState)  # type: ignore[type-arg]

    builder.add_node("load_ticker_context", load_ticker_context)
    builder.add_node("retrieve_memory", retrieve_memory)
    builder.add_node("fetch_market_data", fetch_fn)
    builder.add_node("compute_signals", signals_fn)
    builder.add_node("neutral_recommendation", neutral_recommendation)
    builder.add_node("personalized_recommendation", personalized_recommendation)
    builder.add_node("persist_results", persist_fn)

    builder.set_entry_point("load_ticker_context")
    builder.add_edge("load_ticker_context", "retrieve_memory")
    builder.add_edge("retrieve_memory", "fetch_market_data")
    builder.add_edge("fetch_market_data", "compute_signals")
    builder.add_edge("compute_signals", "neutral_recommendation")
    builder.add_edge("neutral_recommendation", "personalized_recommendation")
    builder.add_edge("personalized_recommendation", "persist_results")
    builder.add_edge("persist_results", END)

    return builder.compile()
