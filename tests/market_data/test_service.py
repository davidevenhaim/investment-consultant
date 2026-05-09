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
