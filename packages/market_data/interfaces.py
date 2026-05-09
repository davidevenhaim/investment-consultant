"""Abstract provider interface for market data."""

import datetime as dt
from abc import ABC, abstractmethod

from market_data.schemas import MarketPriceBar


class MarketDataProvider(ABC):
    """Fetch historical OHLCV data. Swap yfinance → Polygon/Tiingo by replacing this."""

    @abstractmethod
    def fetch_historical_prices(
        self,
        symbol: str,
        start_date: dt.date,
        end_date: dt.date,
    ) -> list[MarketPriceBar]:
        """Return daily OHLCV bars for symbol in [start_date, end_date], ascending."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...
