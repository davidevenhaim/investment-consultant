"""FakeNewsProvider — deterministic in-memory news for tests. No network calls."""

import datetime as dt

from news.interfaces import NewsProvider
from news.schemas import NewsArticle

_FAKE_ARTICLES: dict[str, list[NewsArticle]] = {
    "AAPL": [
        NewsArticle(
            provider_article_id="aapl-001",
            url="https://example.com/aapl-earnings-beat",
            title="Apple beats Q1 earnings expectations on strong iPhone demand",
            description="Apple Inc. reported strong quarterly earnings driven by iPhone sales.",
            source_name="Financial Times",
            author="Jane Doe",
            published_at=dt.datetime(2026, 5, 1, 9, 0, tzinfo=dt.UTC),
            sentiment_score=0.7,
            relevance_score=0.9,
            importance_score=0.8,
        ),
        NewsArticle(
            provider_article_id="aapl-002",
            url="https://example.com/aapl-services-growth",
            title="Apple Services revenue hits record high in fiscal Q1",
            description="Services segment grows 25% year-over-year.",
            source_name="Bloomberg",
            author="John Smith",
            published_at=dt.datetime(2026, 5, 2, 10, 0, tzinfo=dt.UTC),
            sentiment_score=0.65,
            relevance_score=0.85,
            importance_score=0.75,
        ),
        NewsArticle(
            provider_article_id="aapl-003",
            url="https://example.com/aapl-china-risk",
            title="Apple faces headwinds in China amid regulatory scrutiny",
            description="Analysts warn of potential revenue pressure in key market.",
            source_name="Reuters",
            author=None,
            published_at=dt.datetime(2026, 5, 3, 11, 0, tzinfo=dt.UTC),
            sentiment_score=-0.4,
            relevance_score=0.8,
            importance_score=0.7,
        ),
    ],
    "NVDA": [
        NewsArticle(
            provider_article_id="nvda-001",
            url="https://example.com/nvda-ai-demand",
            title="NVIDIA data center revenue surges on AI chip demand",
            description="H100 and Blackwell chip demand continues to outpace supply.",
            source_name="CNBC",
            author="Tech Reporter",
            published_at=dt.datetime(2026, 5, 1, 8, 0, tzinfo=dt.UTC),
            sentiment_score=0.85,
            relevance_score=0.95,
            importance_score=0.9,
        ),
    ],
}


class FakeNewsProvider(NewsProvider):
    """Deterministic in-memory news provider. Never makes network calls."""

    def __init__(self, articles: dict[str, list[NewsArticle]] | None = None) -> None:
        self._articles = articles or _FAKE_ARTICLES

    @property
    def provider_name(self) -> str:
        return "fake"

    async def fetch_news(
        self,
        symbol: str,
        company_name: str | None = None,
        days: int = 14,
        max_articles: int = 20,
    ) -> list[NewsArticle]:
        return self._articles.get(symbol.upper(), [])[:max_articles]
