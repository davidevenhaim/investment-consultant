"""Market data endpoint — minimal read-only view of stored price history."""

from typing import Any

from core.responses import api_response
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Request
from market_data.repository import MarketPriceRepository
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/market-data", tags=["market-data"])


@router.get("/{symbol}/latest")
async def get_market_data_latest(
    symbol: str,
    request: Request,
    provider: str = "yfinance",
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    repo = MarketPriceRepository(db)
    sym = symbol.upper()
    latest_date = await repo.latest_date(sym, provider)
    if latest_date is None:
        raise HTTPException(status_code=404, detail=f"No price data for {sym}")

    bars = await repo.get_bars(sym, provider)
    latest_bar = bars[-1] if bars else None

    return api_response(
        {
            "symbol": sym,
            "latest_price_date": latest_date.isoformat(),
            "latest_close": latest_bar.close if latest_bar else None,
            "bar_count": len(bars),
            "provider": provider,
        },
        request,
    )
