"""yfinance implementation of MarketDataProvider."""

import datetime as dt

import yfinance as yf
from core.errors import MarketDataError
from core.logging import get_logger

from market_data.interfaces import MarketDataProvider
from market_data.schemas import MarketPriceBar

logger = get_logger(__name__)


class YFinanceProvider(MarketDataProvider):
    @property
    def provider_name(self) -> str:
        return "yfinance"

    def fetch_historical_prices(
        self,
        symbol: str,
        start_date: dt.date,
        end_date: dt.date,
    ) -> list[MarketPriceBar]:
        sym = symbol.upper()
        try:
            ticker = yf.Ticker(sym)
            df = ticker.history(
                start=start_date.isoformat(),
                end=(end_date + dt.timedelta(days=1)).isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=False,
            )
        except Exception as exc:
            raise MarketDataError(
                f"yfinance fetch failed for {sym}: {exc}",
                {"symbol": sym, "provider": "yfinance"},
            ) from exc

        if df is None or df.empty:
            logger.warning("yfinance_empty_response", symbol=sym)
            return []

        bars: list[MarketPriceBar] = []
        for idx, row in df.iterrows():
            price_date = (
                idx.date() if hasattr(idx, "date") else dt.date.fromisoformat(str(idx)[:10])
            )
            try:
                bar = MarketPriceBar(
                    symbol=sym,
                    price_date=price_date,
                    open=float(row["Open"]),
                    high=float(row["High"]),
                    low=float(row["Low"]),
                    close=float(row["Close"]),
                    adjusted_close=float(row["Adj Close"]) if "Adj Close" in row else None,
                    volume=int(row["Volume"]) if row["Volume"] > 0 else None,
                    provider="yfinance",
                )
                bars.append(bar)
            except Exception as exc:
                logger.warning(
                    "yfinance_bar_parse_error",
                    symbol=sym,
                    date=str(price_date),
                    error=str(exc),
                )
                continue

        logger.info("yfinance_fetch_ok", symbol=sym, bars=len(bars))
        return sorted(bars, key=lambda b: b.price_date)
