"""FetchNews — fetches and scores news articles for the research run."""

import datetime as dt
from collections.abc import Callable
from typing import Any

from core.logging import get_logger
from news.interfaces import NewsProvider
from news.service import fetch_news_for_symbol
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.state import ResearchState

logger = get_logger(__name__)


def make_fetch_news(
    session: AsyncSession,
    news_provider: NewsProvider | None = None,
) -> Callable[[ResearchState], Any]:
    """Factory: bind DB session and optional provider override into node closure."""

    async def fetch_news(state: ResearchState) -> dict[str, Any]:
        symbol = state["symbol"]
        as_of_date_str: str | None = state.get("as_of_date")
        as_of_date: dt.date | None = (
            dt.date.fromisoformat(as_of_date_str) if as_of_date_str else None
        )
        try:
            articles, score_result = await fetch_news_for_symbol(
                session=session,
                symbol=symbol,
                provider=news_provider,
                as_of_date=as_of_date,
            )
            logger.info(
                "node_fetch_news_ok",
                symbol=symbol,
                score=score_result.score,
                article_count=score_result.article_count,
                as_of_date=as_of_date_str,
            )
            return {
                "news_items": [a.model_dump() for a in articles],
                "news_score_result": score_result,
            }
        except Exception as exc:
            logger.warning("node_fetch_news_failed", symbol=symbol, error=str(exc))
            from news.schemas import NewsScoreResult
            from news.scoring import _NO_DATA_SCORE

            return {
                "news_items": [],
                "news_score_result": NewsScoreResult(
                    score=_NO_DATA_SCORE,
                    no_data=True,
                    reason=f"News node failed: {exc}",
                ),
                "errors": [f"fetch_news_failed: {exc}"],
            }

    return fetch_news
