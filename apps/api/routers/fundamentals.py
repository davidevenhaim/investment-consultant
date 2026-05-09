"""Fundamentals endpoint — read-only view of stored company fundamentals."""
from typing import Any

from core.responses import api_response
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Request
from fundamentals.repository import CompanyFundamentalsRepository
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/fundamentals", tags=["fundamentals"])


@router.get("/{symbol}/latest")
async def get_fundamentals_latest(
    symbol: str,
    request: Request,
    provider: str = "yfinance",
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    repo = CompanyFundamentalsRepository(db)
    snapshot = await repo.get_latest(symbol.upper(), provider)
    if snapshot is None:
        raise HTTPException(status_code=404, detail=f"No fundamentals for {symbol.upper()}")

    return api_response(
        {
            "symbol": snapshot.symbol,
            "as_of_date": snapshot.as_of_date.isoformat(),
            "provider": snapshot.provider,
            "trailing_pe": snapshot.trailing_pe,
            "forward_pe": snapshot.forward_pe,
            "revenue_growth": snapshot.revenue_growth,
            "earnings_growth": snapshot.earnings_growth,
            "profit_margins": snapshot.profit_margins,
            "return_on_equity": snapshot.return_on_equity,
            "debt_to_equity": snapshot.debt_to_equity,
            "price_to_book": snapshot.price_to_book,
            "market_cap": snapshot.market_cap,
            # field_completeness: fraction of key scoring fields populated (0.0–1.0).
            # Measures data completeness, NOT institutional data reliability.
            "field_completeness": snapshot.completeness_score,
        },
        request,
    )
