"""News ingestion service — fetches, scores, and persists news articles."""

import datetime as dt
from datetime import UTC

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
    as_of_date: dt.date | None = None,
) -> tuple[list[NewsArticle], NewsScoreResult]:
    """
    Fetch, persist, deduplicate, and score news for a symbol.
    Returns (articles, score_result).
    Never raises — returns empty result on failure.

    ``as_of_date`` enables historical-replay mode: the external provider is
    skipped (it would return current articles) and the DB is queried for
    articles whose ``published_at`` is on or before ``as_of_date``.
    For live runs, pass ``None`` (default).
    """
    settings = get_settings()

    if not settings.news_enabled and provider is None and as_of_date is None:
        logger.info("news_disabled", symbol=symbol)
        from news.scoring import _NO_DATA_SCORE

        return [], NewsScoreResult(
            score=_NO_DATA_SCORE,
            no_data=True,
            reason="News disabled (NEWS_ENABLED=false).",
        )

    # ── Historical-replay path ────────────────────────────────────────────────
    # Skip the external provider (it returns today's articles) and read only
    # DB-stored articles published up to as_of_date.
    if as_of_date is not None:
        end_dt = dt.datetime.combine(as_of_date, dt.time.max).replace(tzinfo=UTC)
        start_dt = end_dt - dt.timedelta(days=settings.news_lookback_days)
        repo = NewsItemRepository(session)
        db_items = await repo.get_recent(
            symbol=symbol,
            since=start_dt,
            until=end_dt,
            max_articles=settings.news_max_articles_per_symbol,
        )
        articles = [
            NewsArticle(
                provider_article_id=item.provider_article_id,
                url=item.url,
                title=item.title,
                description=item.description,
                source_name=item.source_name,
                author=item.author,
                published_at=item.published_at,
                sentiment_score=float(item.sentiment_score or 0.0),
                relevance_score=float(item.relevance_score or 0.0),
                importance_score=float(item.importance_score or 0.0),
                is_duplicate=bool(item.is_duplicate),
            )
            for item in db_items
        ]
        score = score_news_articles(articles)
        logger.info(
            "news_fetched_historical",
            symbol=symbol,
            as_of_date=as_of_date.isoformat(),
            count=len(articles),
            score=score.score,
        )
        return articles, score

    # ── Live path (current run) ───────────────────────────────────────────────
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
