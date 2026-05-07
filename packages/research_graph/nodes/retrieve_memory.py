"""RetrieveMemory — ChromaDB retrieval stub. Implemented fully in M6."""
from typing import Any

from core.logging import get_logger

from research_graph.state import ResearchState

logger = get_logger(__name__)


def retrieve_memory(state: ResearchState) -> dict[str, Any]:
    """
    Retrieve previous thesis, last recommendation, and past mistakes from ChromaDB.
    ChromaDB integration is implemented in M6. Returns empty stubs here.
    """
    logger.info("node_retrieve_memory", symbol=state["symbol"], note="stub_m6")
    return {
        "previous_thesis": None,
        "last_recommendation": None,
        "past_mistakes": [],
    }
