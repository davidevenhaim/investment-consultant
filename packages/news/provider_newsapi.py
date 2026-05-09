"""NewsAPI provider — fetches news articles from newsapi.org."""

import datetime as dt
import hashlib
from datetime import UTC, datetime

import httpx
from core.logging import get_logger

from news.interfaces import NewsProvider
from news.schemas import NewsArticle

logger = get_logger(__name__)

_NEWSAPI_ENDPOINT = "https://newsapi.org/v2/everything"
_DEFAULT_SENTIMENT = 0.0
_DEFAULT_RELEVANCE = 0.6
_DEFAULT_IMPORTANCE = 0.5


class NewsAPIProvider(NewsProvider):
    """Fetch news from newsapi.org. Requires a valid API key."""

    def __init__(
        self,
        api_key: str,
        timeout_seconds: int = 20,
    ) -> None:
        self._api_key = api_key
        self._timeout = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "newsapi"

    async def fetch_news(
        self,
        symbol: str,
        company_name: str | None = None,
        days: int = 14,
        max_articles: int = 20,
    ) -> list[NewsArticle]:
        query = company_name or symbol
        from_date = (datetime.now(UTC) - dt.timedelta(days=days)).strftime("%Y-%m-%d")

        params: dict[str, str | int] = {
            "q": query,
            "from": from_date,
            "sortBy": "relevancy",
            "language": "en",
            "pageSize": min(max_articles, 100),
            "apiKey": self._api_key,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(_NEWSAPI_ENDPOINT, params=params)
            resp.raise_for_status()
            data = resp.json()

        articles: list[NewsArticle] = []
        for raw in (data.get("articles") or []):
            url = raw.get("url") or ""
            if not url:
                continue
            article_id = hashlib.sha256(url.encode()).hexdigest()[:24]
            pub_str = raw.get("publishedAt") or ""
            try:
                published_at = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                published_at = datetime.now(UTC)

            # Simple heuristic sentiment scoring based on title keywords
            title = (raw.get("title") or "").lower()
            sentiment = _heuristic_sentiment(title)

            articles.append(
                NewsArticle(
                    provider_article_id=article_id,
                    url=url,
                    title=raw.get("title") or "",
                    description=raw.get("description"),
                    source_name=(raw.get("source") or {}).get("name") or "Unknown",
                    author=raw.get("author"),
                    published_at=published_at,
                    sentiment_score=sentiment,
                    relevance_score=_DEFAULT_RELEVANCE,
                    importance_score=_DEFAULT_IMPORTANCE,
                )
            )

        logger.info(
            "newsapi_fetched",
            symbol=symbol,
            count=len(articles),
            query=query,
        )
        return articles[:max_articles]


_POSITIVE_WORDS = frozenset({
    "beat", "beats", "surge", "surges", "soar", "soars", "record", "growth",
    "profit", "gain", "rally", "strong", "bullish", "upgrade", "raises",
    "exceeds", "outperform", "buy", "positive", "higher", "upside",
})
_NEGATIVE_WORDS = frozenset({
    "miss", "misses", "decline", "declines", "fall", "falls", "loss", "losses",
    "downgrade", "cut", "cuts", "warn", "warns", "risk", "risks", "concern",
    "bearish", "sell", "lower", "downside", "struggle", "struggles", "lawsuit",
    "layoff", "layoffs", "recall", "investigation", "fraud",
})


def _heuristic_sentiment(title_lower: str) -> float:
    """Simple keyword-based sentiment: +0.5 positive, -0.5 negative, 0 neutral."""
    words = set(title_lower.split())
    pos = len(words & _POSITIVE_WORDS)
    neg = len(words & _NEGATIVE_WORDS)
    if pos > neg:
        return min(0.7, 0.3 + pos * 0.2)
    if neg > pos:
        return max(-0.7, -0.3 - neg * 0.2)
    return 0.0
