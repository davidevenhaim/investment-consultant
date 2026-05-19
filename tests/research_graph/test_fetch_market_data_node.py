"""Tests for fetch_market_data graph node — as_of_date (M12.2)."""

import datetime as dt

import pytest
from market_data.repository import MarketPriceRepository
from market_data.schemas import MarketPriceBar
from research_graph.nodes.fetch_market_data import make_fetch_market_data


def _make_bars(
    symbol: str,
    start: dt.date,
    n: int,
    provider: str = "mock",
) -> list[MarketPriceBar]:
    """Generate n consecutive weekday bars starting at start."""
    bars = []
    current = start
    for i in range(n):
        while current.weekday() >= 5:
            current += dt.timedelta(days=1)
        bars.append(
            MarketPriceBar(
                symbol=symbol,
                price_date=current,
                open=100.0,
                high=101.0,
                low=99.0,
                close=100.0 + i * 0.1,
                adjusted_close=100.0 + i * 0.1,
                volume=1_000_000,
                provider=provider,
            )
        )
        current += dt.timedelta(days=1)
    return bars


def _make_state(symbol: str = "AAPL", as_of_date: str | None = None) -> dict:
    return {
        "symbol": symbol,
        "run_id": "00000000-0000-0000-0000-000000000001",
        "run_ticker_id": "00000000-0000-0000-0000-000000000002",
        "as_of_time": dt.datetime(2026, 5, 17, tzinfo=dt.UTC),
        "as_of_date": as_of_date,
        "strategy_version": "v0.1.0",
        "prompt_version": "v0.1.0",
        "strategy_config": {},
        "ohlcv": None,
        "errors": [],
        "confidence_penalties": [],
        "data_quality_score": 1.0,
    }


@pytest.mark.asyncio
async def test_fetch_market_data_node_as_of_date_caps_bars(db_session) -> None:
    """OHLCV in state must not contain bars after as_of_date."""
    repo = MarketPriceRepository(db_session)
    cutoff = dt.date(2024, 6, 30)

    # Seed bars: before AND after cutoff
    before = _make_bars("AAPL", start=dt.date(2024, 1, 2), n=120)  # ends ~Jun 2024
    after = _make_bars("AAPL", start=dt.date(2024, 8, 1), n=40)  # Aug–Sep 2024
    await repo.upsert_bars(before + after)

    state = _make_state("AAPL", as_of_date=str(cutoff))
    node = make_fetch_market_data(db_session, provider=None)
    result = await node(state)

    ohlcv = result.get("ohlcv")
    assert ohlcv is not None and not ohlcv.empty, "Node should return OHLCV"
    max_date = max(ohlcv.index)
    assert max_date <= cutoff, f"OHLCV contains bars after as_of_date: {max_date}"


@pytest.mark.asyncio
async def test_fetch_market_data_node_latest_bar_is_as_of_date_or_before(db_session) -> None:
    """Latest bar used for scoring must be <= as_of_date."""
    repo = MarketPriceRepository(db_session)
    cutoff = dt.date(2023, 12, 31)

    bars = _make_bars("NVDA", start=dt.date(2023, 1, 2), n=260)
    await repo.upsert_bars(bars)

    state = _make_state("NVDA", as_of_date=str(cutoff))
    node = make_fetch_market_data(db_session, provider=None)
    result = await node(state)

    ohlcv = result["ohlcv"]
    assert not ohlcv.empty
    assert max(ohlcv.index) <= cutoff


@pytest.mark.asyncio
async def test_fetch_market_data_node_no_as_of_date_returns_all_bars(db_session) -> None:
    """Live run (as_of_date=None) is unchanged — returns all available bars."""
    repo = MarketPriceRepository(db_session)
    bars = _make_bars("MSFT", start=dt.date(2023, 1, 2), n=260)
    await repo.upsert_bars(bars)

    state_live = _make_state("MSFT", as_of_date=None)
    node = make_fetch_market_data(db_session, provider=None)
    result = await node(state_live)

    ohlcv = result["ohlcv"]
    assert not ohlcv.empty
    # All seeded bars should be present (no artificial cap)
    assert len(ohlcv) >= 200


@pytest.mark.asyncio
async def test_fetch_market_data_node_future_bars_ignored_when_as_of_date_set(db_session) -> None:
    """Even when DB holds bars up to today, replay state uses only bars <= as_of_date."""
    repo = MarketPriceRepository(db_session)
    # Simulate having "current" bars in DB
    current_bars = _make_bars("SPY", start=dt.date(2022, 1, 3), n=800)  # ~3 years of data
    await repo.upsert_bars(current_bars)

    # Most recent bar in DB
    all_dates = [b.price_date for b in current_bars]
    db_latest = max(all_dates)

    replay_cutoff = dt.date(2023, 6, 30)
    assert replay_cutoff < db_latest, "Test requires DB to have bars beyond the replay cutoff"

    state = _make_state("SPY", as_of_date=str(replay_cutoff))
    node = make_fetch_market_data(db_session, provider=None)
    result = await node(state)

    ohlcv = result["ohlcv"]
    assert not ohlcv.empty
    assert max(ohlcv.index) <= replay_cutoff
