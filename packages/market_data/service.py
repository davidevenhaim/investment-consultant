"""Market data ingestion service — ensures price history exists and returns it."""
import datetime as dt

from core.logging import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

from market_data.interfaces import MarketDataProvider
from market_data.repository import MarketPriceRepository
from market_data.schemas import MarketPriceBar
from market_data.yfinance_provider import YFinanceProvider

logger = get_logger(__name__)

_TRADING_DAYS_PER_YEAR = 252
_MIN_BARS_3Y = _TRADING_DAYS_PER_YEAR * 3
_MIN_BARS_1Y = _TRADING_DAYS_PER_YEAR * 1

# Refresh if latest bar is more than this many calendar days old
_STALE_THRESHOLD_DAYS = 2


def _default_provider() -> MarketDataProvider:
    return YFinanceProvider()


async def ensure_price_history(
    session: AsyncSession,
    symbol: str,
    years: int = 5,
    provider: MarketDataProvider | None = None,
) -> list[MarketPriceBar]:
    """
    Ensure `years` of daily price history exists in DB for symbol.
    Fetches from provider if data is missing or stale. Returns all stored bars ascending.
    """
    if provider is None:
        provider = _default_provider()

    repo = MarketPriceRepository(session)
    sym = symbol.upper()
    today = dt.date.today()
    required_start = today - dt.timedelta(days=years * 366)

    latest = await repo.latest_date(sym, provider.provider_name)
    needs_fetch = latest is None or (today - latest).days > _STALE_THRESHOLD_DAYS

    if needs_fetch:
        fetch_start = required_start if latest is None else latest - dt.timedelta(days=5)
        fetch_end = today
        logger.info(
            "market_data_fetching",
            symbol=sym,
            start=fetch_start.isoformat(),
            end=fetch_end.isoformat(),
            provider=provider.provider_name,
        )
        bars = provider.fetch_historical_prices(sym, fetch_start, fetch_end)
        if bars:
            inserted = await repo.upsert_bars(bars)
            logger.info("market_data_upserted", symbol=sym, rows=inserted)
        else:
            logger.warning("market_data_empty", symbol=sym)

    return await repo.get_bars(sym, provider.provider_name, start_date=required_start)


def compute_data_quality(bars: list[MarketPriceBar]) -> float:
    """Score 0.0–1.0 based on how much price history exists."""
    n = len(bars)
    if n >= _MIN_BARS_3Y:
        return 0.95
    if n >= _MIN_BARS_1Y:
        return 0.80
    if n > 0:
        return 0.50
    return 0.0
