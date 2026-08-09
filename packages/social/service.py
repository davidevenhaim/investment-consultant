"""Social ingestion service — fetches, scores, and persists social posts."""

import datetime as dt
from datetime import UTC

from core.config import get_settings
from core.logging import get_logger
from db.models import SocialPost
from sqlalchemy.ext.asyncio import AsyncSession

from social.interfaces import SocialProvider
from social.repository import SocialPostRepository
from social.schemas import SocialPostData, SocialScoreResult
from social.scoring import _NO_DATA_SCORE, score_social_posts

logger = get_logger(__name__)


def _default_provider() -> SocialProvider:
    """Provider factory — maps social_provider setting string to concrete class."""
    settings = get_settings()
    name = settings.social_provider.lower()
    if name == "stocktwits":
        from social.provider_stocktwits import StockTwitsProvider

        return StockTwitsProvider(timeout_seconds=settings.social_timeout_seconds)
    raise ValueError(f"Unknown social_provider: {name!r}. Supported: 'stocktwits'")


def _row_to_post(item: SocialPost) -> SocialPostData:
    return SocialPostData(
        provider_post_id=item.provider_post_id,
        author_handle=item.author_handle,
        body=item.body,
        url=item.url,
        posted_at=item.posted_at,
        sentiment_score=float(item.sentiment_score or 0.0),
        likes_count=int(item.likes_count),
        reposts_count=int(item.reposts_count),
        replies_count=item.replies_count,
        is_duplicate=bool(item.is_duplicate),
    )


async def fetch_social_for_symbol(
    session: AsyncSession,
    symbol: str,
    provider: SocialProvider | None = None,
    as_of_date: dt.date | None = None,
) -> tuple[list[SocialPostData], SocialScoreResult]:
    """
    Fetch, persist, and score social posts for a symbol.
    Returns (posts, score_result).
    Never raises — returns empty result on failure.

    ``as_of_date`` enables historical-replay mode: the external provider is
    skipped and the DB is queried for posts posted on or before ``as_of_date``.

    Live mode fetches from the configured provider (StockTwits), persists,
    then re-reads recent posts across ALL providers so host-scraped X posts
    stored in the DB are merged into the scored set.
    """
    settings = get_settings()

    if not settings.social_enabled and provider is None and as_of_date is None:
        logger.info("social_disabled", symbol=symbol)
        return [], SocialScoreResult(
            score=_NO_DATA_SCORE,
            no_data=True,
            reason="Social disabled (SOCIAL_ENABLED=false).",
        )

    repo = SocialPostRepository(session)
    lookback = dt.timedelta(days=settings.social_lookback_days)
    max_posts = settings.social_max_posts_per_symbol

    # ── Historical-replay path ────────────────────────────────────────────────
    if as_of_date is not None:
        end_dt = dt.datetime.combine(as_of_date, dt.time.max).replace(tzinfo=UTC)
        start_dt = end_dt - lookback
        db_items = await repo.get_recent(
            symbol=symbol, since=start_dt, until=end_dt, max_posts=max_posts
        )
        posts = [_row_to_post(item) for item in db_items]
        score = score_social_posts(posts)
        logger.info(
            "social_fetched_historical",
            symbol=symbol,
            as_of_date=as_of_date.isoformat(),
            count=len(posts),
            score=score.score,
        )
        return posts, score

    # ── Live path (current run) ───────────────────────────────────────────────
    p = provider or _default_provider()

    fetched: list[SocialPostData] = []
    try:
        fetched = await p.fetch_posts(
            symbol=symbol,
            days=settings.social_lookback_days,
            max_posts=max_posts,
        )
        logger.info(
            "social_fetched", symbol=symbol, provider=p.provider_name, count=len(fetched)
        )
    except Exception as exc:
        logger.warning("social_fetch_failed", symbol=symbol, error=str(exc))

    # Persist to DB (best-effort, do not fail the run)
    if fetched:
        try:
            await repo.upsert_posts(symbol=symbol, provider=p.provider_name, posts=fetched)
        except Exception as exc:
            logger.warning("social_persist_failed", symbol=symbol, error=str(exc))

    # Merge with DB-stored posts from other providers (e.g. host-scraped X)
    posts = fetched
    try:
        since = dt.datetime.now(UTC) - lookback
        db_items = await repo.get_recent(symbol=symbol, since=since, max_posts=max_posts)
        if db_items:
            posts = [_row_to_post(item) for item in db_items]
    except Exception as exc:
        logger.warning("social_db_read_failed", symbol=symbol, error=str(exc))

    if not posts:
        return [], SocialScoreResult(
            score=_NO_DATA_SCORE,
            no_data=True,
            reason="No social posts available (fetch failed or empty).",
        )

    score = score_social_posts(posts)
    logger.info(
        "social_scored",
        symbol=symbol,
        score=score.score,
        post_count=score.post_count,
        positive=score.positive_count,
        negative=score.negative_count,
    )
    return posts, score
