"""Build the M9 research graph.

Session-in-closure pattern: nodes needing DB get it bound via factory functions.
Graph shape is always stable — every node runs (returns stubs if disabled).
"""
from typing import Any

from ai.interfaces import LLMClient
from fundamentals.interfaces import FundamentalsProvider
from langgraph.graph import END, StateGraph
from market_data.interfaces import MarketDataProvider
from memory.interfaces import MemoryStore
from news.interfaces import NewsProvider
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.nodes.compute_signals import make_compute_signals
from research_graph.nodes.fetch_fundamentals import make_fetch_fundamentals
from research_graph.nodes.fetch_market_data import make_fetch_market_data
from research_graph.nodes.fetch_news import make_fetch_news
from research_graph.nodes.llm_analysis import make_llm_analysis
from research_graph.nodes.load_portfolio_context import make_load_portfolio_context
from research_graph.nodes.load_ticker_context import load_ticker_context
from research_graph.nodes.neutral_recommendation import neutral_recommendation
from research_graph.nodes.persist_results import make_persist_results
from research_graph.nodes.personalized_recommendation import personalized_recommendation
from research_graph.nodes.retrieve_memory import make_retrieve_memory
from research_graph.state import ResearchState


def build_graph_for_session(
    session: AsyncSession,
    market_provider: MarketDataProvider | None = None,
    fundamentals_provider: FundamentalsProvider | None = None,
    memory_store: MemoryStore | None = None,
    llm_client: LLMClient | None = None,
    news_provider: NewsProvider | None = None,
) -> Any:
    """
    Compile research graph with DB session bound into all DB-dependent nodes.
    All providers may be injected for testing; defaults to live implementations.

    Graph (M9):
    LoadTickerContext → RetrieveMemory → FetchMarketData → ComputeSignals
    → FetchFundamentals → FetchNews → LLMAnalysis → NeutralRecommendation
    → LoadPortfolioContext → PersonalizedRecommendation → PersistResults
    """
    fetch_fn: Any = make_fetch_market_data(session, market_provider)
    signals_fn: Any = make_compute_signals(session, market_provider)
    fundamentals_fn: Any = make_fetch_fundamentals(session, fundamentals_provider)
    news_fn: Any = make_fetch_news(session, news_provider)
    retrieve_fn: Any = make_retrieve_memory(store=memory_store)
    llm_fn: Any = make_llm_analysis(session, llm_client=llm_client)
    portfolio_fn: Any = make_load_portfolio_context(session)
    persist_fn: Any = make_persist_results(session, memory_store=memory_store)

    builder: StateGraph = StateGraph(ResearchState)  # type: ignore[type-arg]

    builder.add_node("load_ticker_context", load_ticker_context)
    builder.add_node("retrieve_memory", retrieve_fn)
    builder.add_node("fetch_market_data", fetch_fn)
    builder.add_node("compute_signals", signals_fn)
    builder.add_node("fetch_fundamentals", fundamentals_fn)
    builder.add_node("fetch_news", news_fn)
    builder.add_node("llm_analysis", llm_fn)
    builder.add_node("neutral_recommendation", neutral_recommendation)
    builder.add_node("load_portfolio_context", portfolio_fn)
    builder.add_node("personalized_recommendation", personalized_recommendation)
    builder.add_node("persist_results", persist_fn)

    builder.set_entry_point("load_ticker_context")
    builder.add_edge("load_ticker_context", "retrieve_memory")
    builder.add_edge("retrieve_memory", "fetch_market_data")
    builder.add_edge("fetch_market_data", "compute_signals")
    builder.add_edge("compute_signals", "fetch_fundamentals")
    builder.add_edge("fetch_fundamentals", "fetch_news")
    builder.add_edge("fetch_news", "llm_analysis")
    builder.add_edge("llm_analysis", "neutral_recommendation")
    builder.add_edge("neutral_recommendation", "load_portfolio_context")
    builder.add_edge("load_portfolio_context", "personalized_recommendation")
    builder.add_edge("personalized_recommendation", "persist_results")
    builder.add_edge("persist_results", END)

    return builder.compile()
