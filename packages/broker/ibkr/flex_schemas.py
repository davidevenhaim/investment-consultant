"""Pydantic schemas for IBKR Flex Query data."""

from __future__ import annotations

import datetime as dt  # noqa: TC003
from typing import Literal

from pydantic import BaseModel, Field


class FlexExecution(BaseModel):
    """Normalized trade record parsed from IBKR Flex XML.

    Maps directly to IBKRExecution for persistence.
    """

    exec_id: str                    # deterministic dedupe key (tradeID or derived)
    account_id_ibkr: str
    symbol: str
    exchange: str | None = None
    side: Literal["BUY", "SELL"]
    quantity: float = Field(gt=0)
    price: float = Field(gt=0)
    commission: float | None = None
    currency: str = "USD"
    executed_at: dt.datetime
    order_ref: str | None = None
    raw_json: dict[str, object] = Field(default_factory=dict)
