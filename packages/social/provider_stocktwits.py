"""StockTwits provider — fetches messages from the public symbol stream API."""

import datetime as dt
from datetime import UTC, datetime
from typing import Any

import httpx
from core.logging import get_logger

from social.interfaces import SocialProvider
from social.schemas import SocialPostData

logger = get_logger(__name__)

_STOCKTWITS_ENDPOINT = "https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
_BULLISH_SENTIMENT = 0.6
_BEARISH_SENTIMENT = -0.6


class StockTwitsProvider(SocialProvider):
    """Fetch messages from the public StockTwits symbol stream (no auth)."""

    def __init__(
        self, timeout_seconds: int = 10, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self._timeout = timeout_seconds
        self._transport = transport

    @property
    def provider_name(self) -> str:
        return "stocktwits"

    async def fetch_posts(
        self,
        symbol: str,
        days: int = 7,
        max_posts: int = 30,
    ) -> list[SocialPostData]:
        url = _STOCKTWITS_ENDPOINT.format(symbol=symbol.upper())
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()

        cutoff = datetime.now(UTC) - dt.timedelta(days=days)
        posts: list[SocialPostData] = []
        for raw in data.get("messages") or []:
            post = _parse_message(raw)
            if post is None or post.posted_at < cutoff:
                continue
            posts.append(post)

        logger.info("stocktwits_fetched", symbol=symbol, count=len(posts))
        return posts[:max_posts]


def _parse_message(raw: dict[str, Any]) -> SocialPostData | None:
    """Map one StockTwits message payload to SocialPostData. None if malformed."""
    message_id = raw.get("id")
    body = raw.get("body") or ""
    if message_id is None or not body:
        return None

    created_str = raw.get("created_at") or ""
    try:
        posted_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if posted_at.tzinfo is None:
        posted_at = posted_at.replace(tzinfo=UTC)

    sentiment_basic = ((raw.get("entities") or {}).get("sentiment") or {}).get("basic")
    if sentiment_basic == "Bullish":
        sentiment = _BULLISH_SENTIMENT
    elif sentiment_basic == "Bearish":
        sentiment = _BEARISH_SENTIMENT
    else:
        sentiment = 0.0

    return SocialPostData(
        provider_post_id=str(message_id),
        author_handle=(raw.get("user") or {}).get("username") or "unknown",
        body=body,
        url=None,
        posted_at=posted_at,
        sentiment_score=sentiment,
        likes_count=int((raw.get("likes") or {}).get("total") or 0),
        reposts_count=int((raw.get("reshares") or {}).get("reshared_count") or 0),
    )
