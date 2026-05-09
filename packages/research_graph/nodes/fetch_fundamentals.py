"""FetchFundamentals — fetches real company fundamentals via fundamentals service."""

from collections.abc import Callable
from typing import Any

from core.logging import get_logger
from fundamentals.interfaces import FundamentalsProvider
from fundamentals.service import ensure_company_fundamentals
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.state import ResearchState

logger = get_logger(__name__)


def make_fetch_fundamentals(
    session: AsyncSession,
    provider: FundamentalsProvider | None = None,
) -> Callable[[ResearchState], Any]:
    """Factory: bind DB session (and optional provider override) into node closure."""

    async def fetch_fundamentals(state: ResearchState) -> dict[str, Any]:
        symbol = state["symbol"]
        try:
            snapshot = await ensure_company_fundamentals(session, symbol, provider=provider)
            dq = snapshot.completeness_score

            logger.info(
                "fetch_fundamentals_ok",
                symbol=symbol,
                completeness=dq,
                provider=snapshot.provider,
                trailing_pe=snapshot.trailing_pe,
                revenue_growth=snapshot.revenue_growth,
            )
            return {
                "fundamentals_snapshot": snapshot,
                "fundamentals_data_quality": dq,
            }

        except Exception as exc:
            logger.warning("fetch_fundamentals_failed", symbol=symbol, error=str(exc))
            return {
                "fundamentals_snapshot": None,
                "fundamentals_data_quality": 0.0,
                "errors": [f"fetch_fundamentals_failed: {exc}"],
                "confidence_penalties": [0.15],
            }

    return fetch_fundamentals
