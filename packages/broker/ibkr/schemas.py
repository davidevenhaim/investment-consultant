"""Pydantic schemas for IBKR data — used across broker + service layers."""

from __future__ import annotations

import datetime as dt  # noqa: TC003 — Pydantic uses at runtime
from typing import Literal

from pydantic import BaseModel, Field


class IBKRExecution(BaseModel):
    exec_id: str
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


class IBKRAccountInfo(BaseModel):
    account_id: str
    net_liquidation: float
    cash_balance: float
    currency: str = "USD"
