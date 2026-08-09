"""Abstract provider interface for social posts."""

from abc import ABC, abstractmethod

from social.schemas import SocialPostData


class SocialProvider(ABC):
    """Fetch social posts for a symbol. Swap StockTwits → other by replacing this."""

    @abstractmethod
    async def fetch_posts(
        self,
        symbol: str,
        days: int = 7,
        max_posts: int = 30,
    ) -> list[SocialPostData]:
        """Return recent social posts for symbol."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...
