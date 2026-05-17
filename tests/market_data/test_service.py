"""Tests for market data service — uses mock provider, requires DB."""

import datetime as dt

import pytest
from market_data.repository import MarketPriceRepository
from market_data.service import compute_data_quality, ensure_price_history
from sqlalchemy.ext.asyncio import AsyncSession

from .conftest import MockProvider, _make_bars


@pytest.mark.asyncio
async def test_ensure_price_history_inserts_bars(
    db_session: AsyncSession, mock_provider: MockProvider
) -> None:
    bars = await ensure_price_history(db_session, "AAPL", years=5, provider=mock_provider)
    assert len(bars) > 0
    assert all(b.symbol == "AAPL" for b in bars)
    assert all(b.provider == "mock" for b in bars)


@pytest.mark.asyncio
async def test_ensure_price_history_idempotent(
    db_session: AsyncSession, mock_provider: MockProvider
) -> None:
    bars1 = await ensure_price_history(db_session, "NVDA", years=5, provider=mock_provider)
    bars2 = await ensure_price_history(db_session, "NVDA", years=5, provider=mock_provider)
    assert len(bars1) == len(bars2)


@pytest.mark.asyncio
async def test_ensure_price_history_ordered_ascending(
    db_session: AsyncSession, mock_provider: MockProvider
) -> None:
    bars = await ensure_price_history(db_session, "MSFT", years=5, provider=mock_provider)
    dates = [b.price_date for b in bars]
    assert dates == sorted(dates)


@pytest.mark.asyncio
async def test_ensure_price_history_unknown_symbol_returns_empty(
    db_session: AsyncSession, mock_provider: MockProvider
) -> None:
    bars = await ensure_price_history(db_session, "ZZZZ", years=5, provider=mock_provider)
    assert bars == []


@pytest.mark.asyncio
async def test_upsert_no_duplicates(db_session: AsyncSession, mock_provider: MockProvider) -> None:
    repo = MarketPriceRepository(db_session)
    bars = _make_bars("AAPL", n=10)
    await repo.upsert_bars(bars)
    await repo.upsert_bars(bars)  # second upsert of same data
    count = await repo.count_bars("AAPL", provider="mock")
    assert count == 10


@pytest.mark.asyncio
async def test_repository_latest_date(
    db_session: AsyncSession, mock_provider: MockProvider
) -> None:
    await ensure_price_history(db_session, "AAPL", years=5, provider=mock_provider)
    repo = MarketPriceRepository(db_session)
    latest = await repo.latest_date("AAPL", provider="mock")
    assert latest is not None
    assert isinstance(latest, dt.date)


# ── data quality ──────────────────────────────────────────────────────────────


def test_data_quality_high() -> None:
    bars = _make_bars("X", n=760)  # > 3y
    assert compute_data_quality(bars) == pytest.approx(0.95)


def test_data_quality_medium() -> None:
    bars = _make_bars("X", n=260)  # 1y
    assert compute_data_quality(bars) == pytest.approx(0.80)


def test_data_quality_low() -> None:
    bars = _make_bars("X", n=50)
    assert compute_data_quality(bars) == pytest.approx(0.50)


def test_data_quality_zero() -> None:
    assert compute_data_quality([]) == pytest.approx(0.0)


# ── as_of_date (M12.2) ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_price_history_as_of_date_caps_returned_bars(
    db_session: AsyncSession,
) -> None:
    """Bars after as_of_date must not be returned even if they exist in DB."""
    repo = MarketPriceRepository(db_session)
    cutoff = dt.date(2024, 6, 30)

    # Seed bars: half before cutoff, half after
    before = _make_bars("TSLA", n=100, start=dt.date(2024, 1, 2))  # ends ~May 2024
    after = _make_bars("TSLA", n=50, start=dt.date(2024, 8, 1))   # Aug–Oct 2024
    await repo.upsert_bars(before + after)

    bars = await ensure_price_history(db_session, "TSLA", years=5, provider=None, as_of_date=cutoff)

    assert len(bars) > 0
    assert all(b.price_date <= cutoff for b in bars), "Future bars leaked through as_of_date filter"


@pytest.mark.asyncio
async def test_ensure_price_history_as_of_date_current_data_not_refetched(
    db_session: AsyncSession, mock_provider: MockProvider
) -> None:
    """When DB already has recent (current) bars, replay with a past as_of_date
    should not trigger a new provider fetch — the existing data covers the range."""
    from market_data.schemas import MarketPriceBar as _Bar

    # Pre-populate current bars (ends today-ish since mock starts from 2020-01-02 + 1300 bars)
    await ensure_price_history(db_session, "AAPL", years=5, provider=mock_provider)

    # Now request same symbol with a past as_of_date — provider should NOT be called again
    call_count = {"n": 0}
    original_fetch = mock_provider.fetch_historical_prices

    def counting_fetch(symbol: str, start: dt.date, end: dt.date) -> list[_Bar]:
        call_count["n"] += 1
        return original_fetch(symbol, start, end)

    mock_provider.fetch_historical_prices = counting_fetch  # type: ignore[method-assign]

    as_of = dt.date(2023, 6, 30)
    bars = await ensure_price_history(
        db_session, "AAPL", years=5, provider=mock_provider, as_of_date=as_of
    )

    assert call_count["n"] == 0, "Provider should not be called when DB has data past as_of_date"
    assert all(b.price_date <= as_of for b in bars)


@pytest.mark.asyncio
async def test_ensure_price_history_no_as_of_date_returns_all_bars(
    db_session: AsyncSession, mock_provider: MockProvider
) -> None:
    """Live runs (as_of_date=None) should return all stored bars without any cap."""
    bars_all = await ensure_price_history(db_session, "NVDA", years=5, provider=mock_provider)
    bars_none = await ensure_price_history(
        db_session, "NVDA", years=5, provider=mock_provider, as_of_date=None
    )
    assert len(bars_all) == len(bars_none)


@pytest.mark.asyncio
async def test_repository_get_bars_end_date_filter(db_session: AsyncSession) -> None:
    """get_bars end_date filter is inclusive of the cutoff date."""
    repo = MarketPriceRepository(db_session)
    cutoff = dt.date(2023, 3, 31)
    bars = _make_bars("SPY", n=90, start=dt.date(2023, 1, 2))  # Jan–Apr 2023
    await repo.upsert_bars(bars)

    filtered = await repo.get_bars("SPY", provider="mock", end_date=cutoff)
    assert len(filtered) > 0
    assert all(b.price_date <= cutoff for b in filtered)
