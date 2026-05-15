"""News router — GET /api/v1/news/{symbol}/latest."""

import datetime as dt
from typing import Any

from core.responses import api_response
from db.session import get_db
from fastapi import APIRouter, Depends, Request
from news.repository import NewsItemRepository
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/news", tags=["news"])


@router.get("/{symbol}/latest")
async def latest_news(
    symbol: str,
    request: Request,
    days: int = 14,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the most recent persisted news articles for a symbol."""
    repo = NewsItemRepository(db)
    end_date = dt.datetime.now(dt.UTC).date()
    start_date = end_date - dt.timedelta(days=days)
    since = dt.datetime.combine(start_date, dt.time.min, tzinfo=dt.UTC)
    items = await repo.get_recent(
        symbol=symbol.upper(),
        since=since,
        max_articles=min(limit, 100),
    )

    data = [
        {
            "id": str(item.id),
            "symbol": item.symbol,
            "provider": item.provider,
            "title": item.title,
            "description": item.description,
            "source_name": item.source_name,
            "author": item.author,
            "url": item.url,
            "published_at": item.published_at.isoformat(),
            "sentiment_score": item.sentiment_score,
            "relevance_score": item.relevance_score,
            "importance_score": item.importance_score,
            "is_duplicate": item.is_duplicate,
            "created_at": item.created_at.isoformat(),
        }
        for item in items
    ]
    return api_response({"articles": data, "count": len(data), "symbol": symbol.upper()}, request)
