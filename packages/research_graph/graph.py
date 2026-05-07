"""Build the M3 research graph.

The persist_results node requires a DB session, so the graph is built once per
API request via build_graph_for_session(session). This binds the session into
the node closure without polluting the state TypedDict with infrastructure objects.
"""
from typing import Any

from langgraph.graph import END, StateGraph
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.nodes import (
    compute_signals,
    fetch_market_data,
    load_ticker_context,
    make_persist_results,
    neutral_recommendation,
    personalized_recommendation,
    retrieve_memory,
)
from research_graph.state import ResearchState


def build_graph_for_session(session: AsyncSession) -> Any:
    """
    Compile the M3 research graph with the DB session bound into persist_results.

    Graph order (per CLAUDE.md M3 simplified graph):
    LoadTickerContext → RetrieveMemory → FetchMarketData → ComputeSignals
    → NeutralRecommendation → PersonalizedRecommendation → PersistResults
    """
    persist_fn: Any = make_persist_results(session)

    builder: StateGraph = StateGraph(ResearchState)  # type: ignore[type-arg]

    builder.add_node("load_ticker_context", load_ticker_context)
    builder.add_node("retrieve_memory", retrieve_memory)
    builder.add_node("fetch_market_data", fetch_market_data)
    builder.add_node("compute_signals", compute_signals)
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
