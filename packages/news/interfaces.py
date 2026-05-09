"""Abstract provider interface for news articles."""

from abc import ABC, abstractmethod

from news.schemas import NewsArticle


class NewsProvider(ABC):
    """Fetch news articles. Swap NewsAPI → Bloomberg by replacing this."""

    @abstractmethod
    async def fetch_news(
        self,
        symbol: str,
        company_name: str | None = None,
        days: int = 14,
        max_articles: int = 20,
    ) -> list[NewsArticle]:
        """Return recent news articles for symbol."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...
