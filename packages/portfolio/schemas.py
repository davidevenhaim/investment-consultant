"""Pydantic schemas for portfolio context used within the research graph."""

import uuid
from typing import Any

from pydantic import BaseModel, Field


class PortfolioPositionContext(BaseModel):
    symbol: str
    quantity: float = 0.0
    average_cost: float | None = None
    current_price: float | None = None
    market_value: float | None = None
    cost_basis: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    weight: float = 0.0


class PortfolioContext(BaseModel):
    """Full portfolio snapshot enriched with symbol-specific data."""

    account_id: uuid.UUID
    snapshot_id: uuid.UUID | None = None
    total_equity: float = 0.0
    total_market_value: float = 0.0
    cash_balance: float = 0.0
    cash_pct: float = 0.0
    number_of_positions: int = 0
    max_position_weight: float = 0.0
    largest_position_symbol: str | None = None
    concentration_score: float = Field(default=0.0, ge=0.0, le=1.0)
    risk_level: str = "MEDIUM"
    min_confidence_to_buy: float = 0.65
    max_single_stock_weight: float = 0.15
    position: PortfolioPositionContext | None = None  # for the queried symbol

    def as_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        if d.get("position"):
            d["current_weight"] = d["position"]["weight"]
            d["current_quantity"] = d["position"]["quantity"]
            d["has_position"] = d["position"]["quantity"] > 0
        else:
            d["current_weight"] = 0.0
            d["current_quantity"] = 0.0
            d["has_position"] = False
        d["account_id"] = str(d["account_id"])
        d["snapshot_id"] = str(d["snapshot_id"]) if d["snapshot_id"] else None
        return d
