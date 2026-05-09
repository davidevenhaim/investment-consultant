"""Domain schemas for company fundamentals — provider-agnostic."""

import datetime as dt
from typing import Any

from pydantic import BaseModel, Field

# Key fields used in scoring — presence/absence drives completeness score
_KEY_FIELDS: tuple[str, ...] = (
    "trailing_pe",
    "revenue_growth",
    "profit_margins",
    "return_on_equity",
    "debt_to_equity",
    "price_to_book",
    "free_cashflow",
)


class CompanyFundamentalsSnapshot(BaseModel):
    symbol: str
    as_of_date: dt.date
    provider: str = "yfinance"

    # Valuation
    market_cap: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    price_to_book: float | None = None
    price_to_sales: float | None = None
    enterprise_to_revenue: float | None = None
    enterprise_to_ebitda: float | None = None

    # Growth
    revenue_growth: float | None = None
    earnings_growth: float | None = None

    # Profitability
    profit_margins: float | None = None
    gross_margins: float | None = None
    operating_margins: float | None = None
    return_on_equity: float | None = None

    # Balance sheet
    debt_to_equity: float | None = None
    current_ratio: float | None = None
    free_cashflow: float | None = None
    total_cash: float | None = None
    total_debt: float | None = None

    raw_json: dict[str, Any] = Field(default_factory=dict)

    @property
    def completeness_score(self) -> float:
        """
        Fraction of key scoring fields that are populated (0.0–1.0).
        This is field completeness — whether the provider returned data for each metric.
        It does NOT measure institutional data reliability or source quality.
        """
        populated = sum(1 for f in _KEY_FIELDS if getattr(self, f, None) is not None)
        return round(populated / len(_KEY_FIELDS), 3)

    @property
    def has_growth_data(self) -> bool:
        return self.revenue_growth is not None or self.earnings_growth is not None

    @property
    def has_valuation_data(self) -> bool:
        return any(
            getattr(self, f) is not None
            for f in ("trailing_pe", "forward_pe", "price_to_book", "price_to_sales")
        )
