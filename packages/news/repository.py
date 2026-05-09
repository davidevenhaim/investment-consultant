"""Repository for news_items table."""

import datetime as dt
import hashlib
from datetime import UTC, datetime
from typing import Any

from db.models import NewsItem
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from news.schemas import NewsArticle


class NewsItemRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_articles(
        self,
        symbol: str,
        provider: str,
        articles: list[NewsArticle],
    ) -> list[NewsItem]:
        """Insert new articles, skip duplicates. Returns persisted rows."""
        if not articles:
            return []

        now = datetime.now(UTC)
        rows: list[dict[str, Any]] = []
        for article in articles:
            rows.append(
                {
                    "symbol": symbol.upper(),
                    "provider": provider,
                    "provider_article_id": article.provider_article_id,
                    "url": article.url,
                    "title": article.title,
                    "description": article.description,
                    "source_name": article.source_name,
                    "author": article.author,
                    "published_at": article.published_at,
                    "fetched_at": now,
                    "raw_json": {},
                    "sentiment_score": article.sentiment_score,
                    "relevance_score": article.relevance_score,
                    "importance_score": article.importance_score,
                    "is_duplicate": article.is_duplicate,
                }
            )

        stmt = (
            pg_insert(NewsItem)
            .values(rows)
            .on_conflict_do_nothing(
                constraint="uq_news_symbol_provider_article"
            )
            .returning(NewsItem)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_recent(
        self,
        symbol: str,
        since: dt.datetime,
        max_articles: int = 20,
    ) -> list[NewsItem]:
        """Return recent articles for symbol, newest first."""
        stmt = (
            select(NewsItem)
            .where(
                NewsItem.symbol == symbol.upper(),
                NewsItem.published_at >= since,
                NewsItem.is_duplicate.is_(False),
            )
            .order_by(NewsItem.published_at.desc())
            .limit(max_articles)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


def _url_to_article_id(url: str) -> str:
    """Stable 16-char ID from URL for deduplication."""
    return hashlib.sha256(url.encode()).hexdigest()[:16]
