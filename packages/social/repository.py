"""Repository for social_posts table."""

import datetime as dt
from datetime import UTC, datetime
from typing import Any

from db.models import SocialPost
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from social.schemas import SocialPostData


class SocialPostRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_posts(
        self,
        symbol: str,
        provider: str,
        posts: list[SocialPostData],
    ) -> list[SocialPost]:
        """Insert new posts, skip duplicates. Returns persisted rows."""
        if not posts:
            return []

        now = datetime.now(UTC)
        rows: list[dict[str, Any]] = []
        for post in posts:
            rows.append(
                {
                    "symbol": symbol.upper(),
                    "provider": provider,
                    "provider_post_id": post.provider_post_id,
                    "author_handle": post.author_handle,
                    "body": post.body,
                    "url": post.url,
                    "posted_at": post.posted_at,
                    "fetched_at": now,
                    "raw_json": {},
                    "sentiment_score": post.sentiment_score,
                    "likes_count": post.likes_count,
                    "reposts_count": post.reposts_count,
                    "replies_count": post.replies_count,
                    "is_duplicate": post.is_duplicate,
                }
            )

        stmt = (
            pg_insert(SocialPost)
            .values(rows)
            .on_conflict_do_nothing(constraint="uq_social_symbol_provider_post")
            .returning(SocialPost)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_recent(
        self,
        symbol: str,
        since: dt.datetime,
        max_posts: int = 30,
        until: dt.datetime | None = None,
    ) -> list[SocialPost]:
        """Return recent posts for symbol across all providers, newest first.

        ``until`` caps the upper bound of ``posted_at``. Pass it for
        historical replay runs so future posts are never included.
        """
        conditions = [
            SocialPost.symbol == symbol.upper(),
            SocialPost.posted_at >= since,
            SocialPost.is_duplicate.is_(False),
        ]
        if until is not None:
            conditions.append(SocialPost.posted_at <= until)
        stmt = (
            select(SocialPost)
            .where(*conditions)
            .order_by(SocialPost.posted_at.desc())
            .limit(max_posts)
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
