"""FetchSocial — fetches and scores social posts for the research run."""

import datetime as dt
from collections.abc import Callable
from typing import Any

from core.logging import get_logger
from social.interfaces import SocialProvider
from social.service import fetch_social_for_symbol
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.state import ResearchState

logger = get_logger(__name__)


def make_fetch_social(
    session: AsyncSession,
    social_provider: SocialProvider | None = None,
) -> Callable[[ResearchState], Any]:
    """Factory: bind DB session and optional provider override into node closure."""

    async def fetch_social(state: ResearchState) -> dict[str, Any]:
        symbol = state["symbol"]
        as_of_date_str: str | None = state.get("as_of_date")
        try:
            as_of_date: dt.date | None = (
                dt.date.fromisoformat(as_of_date_str) if as_of_date_str else None
            )
            posts, score_result = await fetch_social_for_symbol(
                session=session,
                symbol=symbol,
                provider=social_provider,
                as_of_date=as_of_date,
            )
            logger.info(
                "node_fetch_social_ok",
                symbol=symbol,
                score=score_result.score,
                post_count=score_result.post_count,
                as_of_date=as_of_date_str,
            )
            return {
                "social_posts": [p.model_dump() for p in posts],
                "social_score_result": score_result,
            }
        except Exception as exc:
            logger.warning("node_fetch_social_failed", symbol=symbol, error=str(exc))
            from social.schemas import SocialScoreResult
            from social.scoring import _NO_DATA_SCORE

            return {
                "social_posts": [],
                "social_score_result": SocialScoreResult(
                    score=_NO_DATA_SCORE,
                    no_data=True,
                    reason=f"Social node failed: {exc}",
                ),
                "errors": [f"fetch_social_failed: {exc}"],
            }

    return fetch_social
