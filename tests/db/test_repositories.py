"""Repository tests and seed idempotency — require DB."""

from datetime import UTC

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_strategy_version_create_and_retrieve(db_session: AsyncSession) -> None:
    from db.repositories import StrategyVersionRepository

    repo = StrategyVersionRepository(db_session)
    sv = await repo.create(version="test-v1.0", description="test", is_active=True)
    assert sv.id is not None
    assert sv.version == "test-v1.0"
    assert sv.is_active is True

    fetched = await repo.get_by_version("test-v1.0")
    assert fetched is not None
    assert fetched.id == sv.id


@pytest.mark.asyncio
async def test_only_one_active_strategy_version(db_session: AsyncSession) -> None:
    from db.repositories import StrategyVersionRepository

    repo = StrategyVersionRepository(db_session)
    await repo.create(version="sv-a", is_active=True)
    sv2 = await repo.create(version="sv-b", is_active=False)
    await repo.activate(sv2.id)

    active = await repo.get_active()
    assert active is not None
    assert active.id == sv2.id


@pytest.mark.asyncio
async def test_watchlist_create_and_deactivate(db_session: AsyncSession) -> None:
    from db.repositories import WatchlistRepository

    repo = WatchlistRepository(db_session)
    ws = await repo.create(symbol="GOOG", company_name="Alphabet")
    assert ws.symbol == "GOOG"
    assert ws.is_active is True

    removed = await repo.deactivate("GOOG")
    assert removed is True

    active = await repo.list_active()
    assert not any(s.symbol == "GOOG" for s in active)


@pytest.mark.asyncio
async def test_research_run_creates_ticker_rows(db_session: AsyncSession) -> None:
    from db.enums import ResearchRunType, TickerRunStatus
    from db.repositories import ResearchRunRepository

    repo = ResearchRunRepository(db_session)
    run = await repo.create(run_type=ResearchRunType.MANUAL)
    tickers = await repo.add_tickers(run.id, ["AAPL", "NVDA", "TSLA"])

    assert len(tickers) == 3
    symbols = {t.symbol for t in tickers}
    assert symbols == {"AAPL", "NVDA", "TSLA"}
    assert all(t.status == TickerRunStatus.CREATED for t in tickers)

    loaded = await repo.get_by_id(run.id)
    assert loaded is not None
    assert len(loaded.tickers) == 3


@pytest.mark.asyncio
async def test_seed_idempotency(db_session: AsyncSession) -> None:
    """Run seed logic twice — counts should not increase second time."""
    from db.models import WatchlistSymbol
    from db.repositories import (
        PromptVersionRepository,
        StrategyVersionRepository,
        WatchlistRepository,
    )

    async def _run_seed() -> None:
        sv_repo = StrategyVersionRepository(db_session)
        if await sv_repo.get_by_version("seed-v0.1") is None:
            await sv_repo.create(version="seed-v0.1", is_active=True)

        pv_repo = PromptVersionRepository(db_session)
        if await pv_repo.get_by_name_version("research", "seed-v0.1") is None:
            await pv_repo.create(name="research", version="seed-v0.1", prompt_text="placeholder")

        wl_repo = WatchlistRepository(db_session)
        for sym in ["AAPL", "NVDA"]:
            if await wl_repo.get_by_symbol(sym) is None:
                await wl_repo.create(symbol=sym)

    await _run_seed()
    result1 = await db_session.execute(
        select(WatchlistSymbol).where(WatchlistSymbol.symbol.in_(["AAPL", "NVDA"]))
    )
    count1 = len(result1.scalars().all())

    await _run_seed()
    result2 = await db_session.execute(
        select(WatchlistSymbol).where(WatchlistSymbol.symbol.in_(["AAPL", "NVDA"]))
    )
    count2 = len(result2.scalars().all())

    assert count1 == count2 == 2


@pytest.mark.asyncio
async def test_neutral_recommendation_score_validation_via_check(db_session: AsyncSession) -> None:
    """DB CHECK constraint rejects out-of-range score."""
    from datetime import datetime

    from db.enums import ResearchRunType
    from db.models import NeutralRecommendation, ResearchRun

    run = ResearchRun(run_type=ResearchRunType.MANUAL.value, status="CREATED")
    db_session.add(run)
    await db_session.flush()

    bad_rec = NeutralRecommendation(
        research_run_id=run.id,
        symbol="AAPL",
        action="HOLD",
        score=150,  # violates CHECK score <= 100
        confidence=0.8,
        final_reason="test",
        as_of_time=datetime.now(UTC),
    )
    db_session.add(bad_rec)
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await db_session.flush()
