"""FakeSocialProvider — deterministic in-memory posts for tests. No network calls."""

import datetime as dt

from social.interfaces import SocialProvider
from social.schemas import SocialPostData

# Dates are relative to now so posts always fall within any reasonable lookback
# window. Fixed calendar dates would drift outside the window and flake.
_NOW = dt.datetime.now(dt.UTC)

_FAKE_POSTS: dict[str, list[SocialPostData]] = {
    "AAPL": [
        SocialPostData(
            provider_post_id="fake-aapl-001",
            author_handle="bullinvestor",
            body="$AAPL services growth is unreal, loading up before earnings",
            posted_at=_NOW - dt.timedelta(days=1),
            sentiment_score=0.6,
            likes_count=42,
            reposts_count=7,
        ),
        SocialPostData(
            provider_post_id="fake-aapl-002",
            author_handle="valuehawk",
            body="$AAPL China numbers worry me, trimming position",
            posted_at=_NOW - dt.timedelta(days=2),
            sentiment_score=-0.6,
            likes_count=15,
            reposts_count=2,
        ),
        SocialPostData(
            provider_post_id="fake-aapl-003",
            author_handle="chartwatcher",
            body="$AAPL consolidating above 200dma, watching for breakout",
            posted_at=_NOW - dt.timedelta(days=3),
            sentiment_score=0.0,
            likes_count=5,
            reposts_count=0,
        ),
    ],
    "NVDA": [
        SocialPostData(
            provider_post_id="fake-nvda-001",
            author_handle="aibull",
            body="$NVDA demand still outpacing supply, this train has no brakes",
            posted_at=_NOW - dt.timedelta(days=1),
            sentiment_score=0.6,
            likes_count=120,
            reposts_count=30,
        ),
    ],
}


class FakeSocialProvider(SocialProvider):
    """Deterministic in-memory social provider. Never makes network calls."""

    def __init__(self, posts: dict[str, list[SocialPostData]] | None = None) -> None:
        self._posts = posts or _FAKE_POSTS

    @property
    def provider_name(self) -> str:
        return "fake"

    async def fetch_posts(
        self,
        symbol: str,
        days: int = 7,
        max_posts: int = 30,
    ) -> list[SocialPostData]:
        return self._posts.get(symbol.upper(), [])[:max_posts]
