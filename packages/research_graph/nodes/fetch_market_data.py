"""FetchMarketData — fetches real OHLCV from DB/yfinance via market_data service."""

import datetime as dt
from collections.abc import Callable
from typing import Any

import pandas as pd
from core.logging import get_logger
from market_data.interfaces import MarketDataProvider
from market_data.service import compute_data_quality, ensure_price_history
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.state import ResearchState

logger = get_logger(__name__)


def make_fetch_market_data(
    session: AsyncSession,
    provider: MarketDataProvider | None = None,
) -> Callable[[ResearchState], Any]:
    """Factory: bind DB session (and optional provider override) into node closure."""

    async def fetch_market_data(state: ResearchState) -> dict[str, Any]:
        symbol = state["symbol"]
        as_of_date_str: str | None = state.get("as_of_date")
        as_of_date: dt.date | None = (
            dt.date.fromisoformat(as_of_date_str) if as_of_date_str else None
        )
        try:
            bars = await ensure_price_history(
                session, symbol, years=5, provider=provider, as_of_date=as_of_date
            )
            dq = compute_data_quality(bars)

            if not bars:
                logger.warning("fetch_market_data_no_data", symbol=symbol)
                return {
                    "ohlcv": pd.DataFrame(),
                    "data_quality_score": 0.0,
                    "errors": [f"fetch_market_data: no price data for {symbol}"],
                    "confidence_penalties": [0.40],
                }

            df = pd.DataFrame(
                [
                    {
                        "date": b.price_date,
                        "open": b.open,
                        "high": b.high,
                        "low": b.low,
                        "close": b.close,
                        "adjusted_close": b.adjusted_close,
                        "volume": b.volume,
                    }
                    for b in bars
                ]
            ).set_index("date")

            logger.info(
                "fetch_market_data_ok",
                symbol=symbol,
                bars=len(bars),
                dq=dq,
                latest=str(bars[-1].price_date),
                as_of_date=as_of_date_str,
            )
            return {"ohlcv": df, "data_quality_score": dq}

        except Exception as exc:
            logger.warning("fetch_market_data_failed", symbol=symbol, error=str(exc))
            return {
                "ohlcv": pd.DataFrame(),
                "data_quality_score": 0.0,
                "errors": [f"fetch_market_data_failed: {exc}"],
                "confidence_penalties": [0.40],
            }

    return fetch_market_data
