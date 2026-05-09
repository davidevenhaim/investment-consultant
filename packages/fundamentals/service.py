"""Fundamentals ingestion service — ensures a recent snapshot exists and returns it."""

import datetime as dt

from core.logging import get_logger
from sqlalchemy.ext.asyncio import AsyncSession

from fundamentals.interfaces import FundamentalsProvider
from fundamentals.repository import CompanyFundamentalsRepository
from fundamentals.schemas import CompanyFundamentalsSnapshot
from fundamentals.yfinance_provider import YFinanceFundamentalsProvider

logger = get_logger(__name__)

_DEFAULT_MAX_AGE_DAYS = 7


def _default_provider() -> FundamentalsProvider:
    return YFinanceFundamentalsProvider()


async def ensure_company_fundamentals(
    session: AsyncSession,
    symbol: str,
    provider: FundamentalsProvider | None = None,
    max_age_days: int = _DEFAULT_MAX_AGE_DAYS,
) -> CompanyFundamentalsSnapshot:
    """
    Return a recent fundamentals snapshot for symbol.
    Fetches from provider and upserts if missing or stale.
    """
    if provider is None:
        provider = _default_provider()

    repo = CompanyFundamentalsRepository(session)
    sym = symbol.upper()
    today = dt.date.today()

    latest_date = await repo.get_latest_date(sym, provider.provider_name)
    needs_fetch = latest_date is None or (today - latest_date).days > max_age_days

    if needs_fetch:
        logger.info("fundamentals_fetching", symbol=sym, provider=provider.provider_name)
        try:
            snapshot = provider.fetch_company_fundamentals(sym)
            await repo.upsert(snapshot)
            logger.info(
                "fundamentals_upserted",
                symbol=sym,
                completeness=snapshot.completeness_score,
            )
            return snapshot
        except Exception as exc:
            logger.warning("fundamentals_fetch_failed", symbol=sym, error=str(exc))
            # Return cached if available, else empty stub
            cached = await repo.get_latest(sym, provider.provider_name)
            if cached is not None:
                logger.info("fundamentals_using_stale_cache", symbol=sym)
                return cached
            return CompanyFundamentalsSnapshot(
                symbol=sym, as_of_date=today, provider=provider.provider_name
            )

    result = await repo.get_latest(sym, provider.provider_name)
    if result is None:
        return CompanyFundamentalsSnapshot(
            symbol=sym, as_of_date=today, provider=provider.provider_name
        )
    return result
