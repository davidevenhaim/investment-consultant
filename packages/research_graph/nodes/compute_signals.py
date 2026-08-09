"""ComputeSignals — real deterministic technical indicators from OHLCV data."""

import datetime as dt
from typing import Any

from core.logging import get_logger
from market_data.indicators import compute_all_signals
from market_data.interfaces import MarketDataProvider
from market_data.service import ensure_price_history
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.state import ResearchState

logger = get_logger(__name__)

_SPY = "SPY"


def make_compute_signals(
    session: AsyncSession,
    provider: MarketDataProvider | None = None,
) -> Any:
    """Factory: bind DB session into node closure for SPY benchmark fetch."""

    async def compute_signals(state: ResearchState) -> dict[str, Any]:
        symbol = state["symbol"]
        ohlcv = state.get("ohlcv")
        as_of_date_str: str | None = state.get("as_of_date")

        try:
            as_of_date: dt.date | None = (
                dt.date.fromisoformat(as_of_date_str) if as_of_date_str else None
            )
            if ohlcv is None or ohlcv.empty:
                logger.warning("compute_signals_no_ohlcv", symbol=symbol)
                return {
                    "technical_signals": None,
                    "errors": [f"compute_signals: no OHLCV for {symbol}"],
                    "confidence_penalties": [0.20],
                }

            closes = ohlcv["close"].tolist()
            highs = ohlcv["high"].tolist()
            lows = ohlcv["low"].tolist()

            # Fetch SPY for relative strength — degrade gracefully if it fails.
            # Pass as_of_date so SPY bars are also capped at the replay date.
            spy_closes: list[float] | None = None
            if symbol != _SPY:
                try:
                    spy_bars = await ensure_price_history(
                        session, _SPY, years=2, provider=provider, as_of_date=as_of_date
                    )
                    if spy_bars:
                        spy_closes = [b.close for b in spy_bars]
                except Exception as spy_exc:
                    logger.warning("compute_signals_spy_failed", error=str(spy_exc))

            signals = compute_all_signals(symbol, closes, highs, lows, spy_closes)

            if spy_closes is None and symbol != _SPY:
                return {
                    "technical_signals": signals,
                    "errors": ["compute_signals: SPY data unavailable, relative strength skipped"],
                    "confidence_penalties": [0.05],
                }

            logger.info(
                "compute_signals_ok",
                symbol=symbol,
                bars=len(closes),
                rsi=signals.get("rsi_14"),
                rs3m=signals.get("relative_strength_3m_vs_spy"),
                as_of_date=as_of_date_str,
            )
            return {"technical_signals": signals}

        except Exception as exc:
            logger.warning("compute_signals_failed", symbol=symbol, error=str(exc))
            return {
                "technical_signals": None,
                "errors": [f"compute_signals_failed: {exc}"],
                "confidence_penalties": [0.20],
            }

    return compute_signals
