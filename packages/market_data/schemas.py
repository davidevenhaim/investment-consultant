"""Domain schemas for market data — provider-agnostic."""

import datetime as dt

from pydantic import BaseModel, Field


class MarketPriceBar(BaseModel):
    symbol: str
    price_date: dt.date
    open: float = Field(gt=0)
    high: float = Field(gt=0)
    low: float = Field(gt=0)
    close: float = Field(gt=0)
    adjusted_close: float | None = None
    volume: int | None = None
    provider: str = "yfinance"
