"""News ingestion service — fetches, scores, and persists news articles."""

from core.config import get_settings
from core.logging import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

from news.interfaces import NewsProvider
from news.repository import NewsItemRepository
from news.schemas import NewsArticle, NewsScoreResult
from news.scoring import score_news_articles

logger = get_logger(__name__)


def _default_provider() -> NewsProvider:
    """Provider factory — maps news_provider setting string to concrete class."""
    settings = get_settings()
    name = settings.news_provider.lower()
    if name == "newsapi":
        from news.provider_newsapi import NewsAPIProvider
        return NewsAPIProvider(
            api_key=settings.newsapi_key,
            timeout_seconds=settings.news_timeout_seconds,
        )
    raise ValueError(f"Unknown news_provider: {name!r}. Supported: 'newsapi'")


async def fetch_news_for_symbol(
    session: AsyncSession,
    symbol: str,
    company_name: str | None = None,
    provider: NewsProvider | None = None,
) -> tuple[list[NewsArticle], NewsScoreResult]:
    """
    Fetch, persist, deduplicate, and score news for a symbol.
    Returns (articles, score_result).
    Never raises — returns empty result on failure.
    """
    settings = get_settings()

    if not settings.news_enabled and provider is None:
        logger.info("news_disabled", symbol=symbol)
        from news.scoring import _NO_DATA_SCORE
        return [], NewsScoreResult(
            score=_NO_DATA_SCORE,
            no_data=True,
            reason="News disabled (NEWS_ENABLED=false).",
        )

    p = provider or _default_provider()

    try:
        articles = await p.fetch_news(
            symbol=symbol,
            company_name=company_name,
            days=settings.news_lookback_days,
            max_articles=settings.news_max_articles_per_symbol,
        )
        logger.info(
            "news_fetched",
            symbol=symbol,
            provider=p.provider_name,
            count=len(articles),
        )
    except Exception as exc:
        logger.warning("news_fetch_failed", symbol=symbol, error=str(exc))
        from news.scoring import _NO_DATA_SCORE
        return [], NewsScoreResult(
            score=_NO_DATA_SCORE,
            no_data=True,
            reason=f"News fetch failed: {exc}",
        )

    # Persist to DB (best-effort, do not fail the run)
    try:
        repo = NewsItemRepository(session)
        await repo.upsert_articles(symbol=symbol, provider=p.provider_name, articles=articles)
    except Exception as exc:
        logger.warning("news_persist_failed", symbol=symbol, error=str(exc))

    score = score_news_articles(articles)
    logger.info(
        "news_scored",
        symbol=symbol,
        score=score.score,
        article_count=score.article_count,
        positive=score.positive_count,
        negative=score.negative_count,
    )
    return articles, score
