"""Abstract provider interface for company fundamentals."""

from abc import ABC, abstractmethod

from fundamentals.schemas import CompanyFundamentalsSnapshot


class FundamentalsProvider(ABC):
    """Fetch company fundamentals. Swap yfinance → Bloomberg by replacing this."""

    @abstractmethod
    def fetch_company_fundamentals(self, symbol: str) -> CompanyFundamentalsSnapshot:
        """Return current fundamentals snapshot for symbol."""
        ...

    @property
    @abstractmethod
    def provider_name(self) -> str: ...
