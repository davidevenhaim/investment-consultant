"""LoadTickerContext — sets as_of_time and validates run context is populated."""

from datetime import UTC, datetime
from typing import Any

from core.logging import get_logger

from research_graph.state import ResearchState

logger = get_logger(__name__)


def load_ticker_context(state: ResearchState) -> dict[str, Any]:
    """
    Set the wall-clock as_of_time for this research run.
    Validate that required context fields are present.
    """
    symbol = state["symbol"]
    logger.info("node_load_ticker_context", symbol=symbol, run_id=state["run_id"])
    return {"as_of_time": datetime.now(UTC)}
