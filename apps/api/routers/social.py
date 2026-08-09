"""Social router — GET /api/v1/social/{symbol}/latest."""

import datetime as dt
from typing import Any

from core.responses import api_response
from db.session import get_db
from fastapi import APIRouter, Depends, Request
from social.repository import SocialPostRepository
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/social", tags=["social"])


@router.get("/{symbol}/latest")
async def latest_social_posts(
    symbol: str,
    request: Request,
    days: int = 7,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the most recent persisted social posts for a symbol."""
    repo = SocialPostRepository(db)
    end_date = dt.datetime.now(dt.UTC).date()
    start_date = end_date - dt.timedelta(days=days)
    since = dt.datetime.combine(start_date, dt.time.min, tzinfo=dt.UTC)
    items = await repo.get_recent(
        symbol=symbol.upper(),
        since=since,
        max_posts=min(limit, 100),
    )

    data = [
        {
            "id": str(item.id),
            "symbol": item.symbol,
            "provider": item.provider,
            "author_handle": item.author_handle,
            "body": item.body,
            "url": item.url,
            "posted_at": item.posted_at.isoformat(),
            "sentiment_score": item.sentiment_score,
            "likes_count": item.likes_count,
            "reposts_count": item.reposts_count,
            "replies_count": item.replies_count,
            "is_duplicate": item.is_duplicate,
            "created_at": item.created_at.isoformat(),
        }
        for item in items
    ]
    return api_response({"posts": data, "count": len(data), "symbol": symbol.upper()}, request)
