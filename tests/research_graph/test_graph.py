"""Integration tests for the full research graph — requires DB."""
import pytest
from db.enums import RecommendationAction, ResearchRunType, TickerRunStatus
from db.models import NeutralRecommendation as NeutralRecModel
from db.models import ResearchRun, ResearchRunTicker
from db.repositories import ResearchRunRepository
from research_graph.graph import build_graph_for_session
from research_graph.runner import make_initial_state, run_research_for_run
from sqlalchemy.ext.asyncio import AsyncSession

from tests.market_data.conftest import MockProvider


async def _make_run_and_ticker(
    session: AsyncSession, symbol: str
) -> tuple[ResearchRun, ResearchRunTicker]:
    repo = ResearchRunRepository(session)
    run = await repo.create(run_type=ResearchRunType.MANUAL)
    tickers = await repo.add_tickers(run.id, [symbol])
    return run, tickers[0]


@pytest.fixture
def provider() -> MockProvider:
    return MockProvider()


@pytest.mark.asyncio
async def test_full_graph_produces_neutral_rec(db_session: AsyncSession, provider: MockProvider) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = build_graph_for_session(db_session, provider)
    initial = make_initial_state(run, ticker, "v0.1.0")
    final = await graph.ainvoke(initial)

    assert final["neutral_rec"] is not None
    assert final["personalized_rec"] is not None
    assert 0 <= final["neutral_rec"].score <= 100
    assert final["neutral_rec"].action in list(RecommendationAction)


@pytest.mark.asyncio
async def test_full_graph_persists_neutral_rec_to_db(
    db_session: AsyncSession, provider: MockProvider
) -> None:
    from sqlalchemy import select

    run, ticker = await _make_run_and_ticker(db_session, "NVDA")
    graph = build_graph_for_session(db_session, provider)
    initial = make_initial_state(run, ticker, "v0.1.0")
    await graph.ainvoke(initial)

    result = await db_session.execute(
        select(NeutralRecModel).where(NeutralRecModel.research_run_id == run.id)
    )
    recs = result.scalars().all()
    assert len(recs) == 1
    assert recs[0].symbol == "NVDA"
    assert recs[0].score > 0


@pytest.mark.asyncio
async def test_full_graph_marks_ticker_completed(
    db_session: AsyncSession, provider: MockProvider
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "TSLA")
    graph = build_graph_for_session(db_session, provider)
    initial = make_initial_state(run, ticker, "v0.1.0")
    await graph.ainvoke(initial)

    await db_session.refresh(ticker)
    assert ticker.status == TickerRunStatus.COMPLETED.value
    assert ticker.finished_at is not None


@pytest.mark.asyncio
async def test_full_graph_no_errors_for_mock_data(
    db_session: AsyncSession, provider: MockProvider
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = build_graph_for_session(db_session, provider)
    initial = make_initial_state(run, ticker, "v0.1.0")
    final = await graph.ainvoke(initial)

    assert final["errors"] == []


@pytest.mark.asyncio
async def test_run_research_for_run_multiple_tickers(
    db_session: AsyncSession, provider: MockProvider
) -> None:
    repo = ResearchRunRepository(db_session)
    run = await repo.create(run_type=ResearchRunType.MANUAL)
    tickers = await repo.add_tickers(run.id, ["AAPL", "NVDA", "TSLA"])

    summary = await run_research_for_run(run, tickers, db_session, "v0.1.0", provider=provider)

    assert summary["symbols_failed"] == []
    assert set(summary["symbols_completed"]) == {"AAPL", "NVDA", "TSLA"}

    for t in tickers:
        await db_session.refresh(t)
        assert t.status == TickerRunStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_price_at_recommendation_persisted(
    db_session: AsyncSession, provider: MockProvider
) -> None:
    from sqlalchemy import select

    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = build_graph_for_session(db_session, provider)
    await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    result = await db_session.execute(
        select(NeutralRecModel).where(NeutralRecModel.research_run_id == run.id)
    )
    rec = result.scalar_one()
    assert rec.price_at_recommendation is not None
    assert float(rec.price_at_recommendation) > 0


@pytest.mark.asyncio
async def test_aapl_score_above_50(db_session: AsyncSession, provider: MockProvider) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = build_graph_for_session(db_session, provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    assert final["neutral_rec"] is not None
    assert final["neutral_rec"].score >= 50


@pytest.mark.asyncio
async def test_data_quality_score_populated(
    db_session: AsyncSession, provider: MockProvider
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = build_graph_for_session(db_session, provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    assert final["data_quality_score"] > 0
