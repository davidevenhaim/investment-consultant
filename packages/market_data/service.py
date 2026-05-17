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
    as_of_date: dt.date | None = None,
) -> list[MarketPriceBar]:
    """
    Ensure `years` of daily price history exists in DB for symbol.
    Fetches from provider if data is missing or stale. Returns all stored bars ascending.

    ``as_of_date`` caps the fetch window and the returned bars so historical replay
    runs never include data after the replay date.  For live runs, pass ``None``
    (default) to use today.
    """
    if provider is None:
        provider = _default_provider()

    repo = MarketPriceRepository(session)
    sym = symbol.upper()
    today = dt.date.today()
    # Reference date: as_of_date for replay, today for live runs.
    ref_date = as_of_date if as_of_date is not None else today
    required_start = ref_date - dt.timedelta(days=years * 366)

    latest = await repo.latest_date(sym, provider.provider_name)
    # Staleness is relative to ref_date.  When latest > ref_date (e.g. current
    # data already in DB for a replay run), the difference is negative, so this
    # evaluates to False — no fetch needed.
    needs_fetch = latest is None or (ref_date - latest).days > _STALE_THRESHOLD_DAYS

    if needs_fetch:
        fetch_start = required_start if latest is None else latest - dt.timedelta(days=5)
        fetch_end = ref_date  # cap at as_of_date for replay; today for live runs
        logger.info(
            "market_data_fetching",
            symbol=sym,
            start=fetch_start.isoformat(),
            end=fetch_end.isoformat(),
            provider=provider.provider_name,
            as_of_date=as_of_date.isoformat() if as_of_date else None,
        )
        bars = provider.fetch_historical_prices(sym, fetch_start, fetch_end)
        if bars:
            inserted = await repo.upsert_bars(bars)
            logger.info("market_data_upserted", symbol=sym, rows=inserted)
        else:
            logger.warning("market_data_empty", symbol=sym)

    # For replay: pass end_date so the returned slice never includes future bars.
    return await repo.get_bars(
        sym, provider.provider_name, start_date=required_start, end_date=as_of_date
    )


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
