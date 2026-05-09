"""RetrieveMemory node — fetches previous research from ChromaDB."""

from collections.abc import Callable
from typing import Any

from core.logging import get_logger
from memory.interfaces import MemoryStore
from memory.retriever import retrieve_symbol_memory

from research_graph.state import ResearchState

logger = get_logger(__name__)


def make_retrieve_memory(store: MemoryStore | None = None) -> Callable[[ResearchState], Any]:
    """Factory that optionally binds a specific MemoryStore for testing."""

    async def retrieve_memory(state: ResearchState) -> dict[str, Any]:
        symbol = state["symbol"]
        logger.info("node_retrieve_memory", symbol=symbol)

        ctx = await retrieve_symbol_memory(symbol, limit=5, store=store)

        prev_rec = ctx.previous_recommendation or {}
        return {
            "memory_context": ctx,
            "memory_count": ctx.memory_count,
            "memory_summary": ctx.memory_summary,
            "previous_thesis": ctx.previous_thesis,
            "last_recommendation": prev_rec if prev_rec else None,
            "past_mistakes": [],
        }

    return retrieve_memory
