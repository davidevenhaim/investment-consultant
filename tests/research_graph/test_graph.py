"""Integration tests for the full research graph — requires DB."""
import pytest
from db.enums import RecommendationAction, ResearchRunType, TickerRunStatus
from db.models import NeutralRecommendation as NeutralRecModel
from db.models import ResearchRun, ResearchRunTicker
from db.repositories import ResearchRunRepository
from research_graph.graph import build_graph_for_session
from research_graph.runner import make_initial_state, run_research_for_run
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tests.fundamentals.conftest import MockFundamentalsProvider
from tests.market_data.conftest import MockProvider


async def _make_run_and_ticker(
    session: AsyncSession, symbol: str
) -> tuple[ResearchRun, ResearchRunTicker]:
    repo = ResearchRunRepository(session)
    run = await repo.create(run_type=ResearchRunType.MANUAL)
    tickers = await repo.add_tickers(run.id, [symbol])
    return run, tickers[0]


@pytest.fixture
def market_provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
def fund_provider() -> MockFundamentalsProvider:
    return MockFundamentalsProvider()


def _graph(session: AsyncSession, mp: MockProvider, fp: MockFundamentalsProvider) -> object:
    return build_graph_for_session(session, market_provider=mp, fundamentals_provider=fp)


@pytest.mark.asyncio
async def test_full_graph_produces_neutral_rec(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    assert final["neutral_rec"] is not None
    assert final["personalized_rec"] is not None
    assert 0 <= final["neutral_rec"].score <= 100
    assert final["neutral_rec"].action in list(RecommendationAction)


@pytest.mark.asyncio
async def test_full_graph_persists_neutral_rec_to_db(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "NVDA")
    graph = _graph(db_session, market_provider, fund_provider)
    await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    result = await db_session.execute(
        select(NeutralRecModel).where(NeutralRecModel.research_run_id == run.id)
    )
    recs = result.scalars().all()
    assert len(recs) == 1
    assert recs[0].symbol == "NVDA"
    assert recs[0].score > 0


@pytest.mark.asyncio
async def test_full_graph_marks_ticker_completed(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "TSLA")
    graph = _graph(db_session, market_provider, fund_provider)
    await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    await db_session.refresh(ticker)
    assert ticker.status == TickerRunStatus.COMPLETED.value
    assert ticker.finished_at is not None


@pytest.mark.asyncio
async def test_full_graph_no_errors_for_mock_data(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    assert final["errors"] == []


@pytest.mark.asyncio
async def test_run_research_for_run_multiple_tickers(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    repo = ResearchRunRepository(db_session)
    run = await repo.create(run_type=ResearchRunType.MANUAL)
    tickers = await repo.add_tickers(run.id, ["AAPL", "NVDA", "TSLA"])

    summary = await run_research_for_run(
        run, tickers, db_session, "v0.1.0",
        market_provider=market_provider,
        fundamentals_provider=fund_provider,
    )

    assert summary["symbols_failed"] == []
    assert set(summary["symbols_completed"]) == {"AAPL", "NVDA", "TSLA"}

    for t in tickers:
        await db_session.refresh(t)
        assert t.status == TickerRunStatus.COMPLETED.value


@pytest.mark.asyncio
async def test_price_at_recommendation_persisted(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    result = await db_session.execute(
        select(NeutralRecModel).where(NeutralRecModel.research_run_id == run.id)
    )
    rec = result.scalar_one()
    assert rec.price_at_recommendation is not None
    assert float(rec.price_at_recommendation) > 0


@pytest.mark.asyncio
async def test_aapl_score_above_50(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    assert final["neutral_rec"] is not None
    assert final["neutral_rec"].score >= 50


@pytest.mark.asyncio
async def test_data_quality_score_populated(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    assert final["data_quality_score"] > 0


@pytest.mark.asyncio
async def test_analysis_completeness_populated(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    assert final["analysis_completeness"] > 0
    assert "news" in final["missing_components"]
    assert "portfolio_context" in final["missing_components"]


@pytest.mark.asyncio
async def test_score_breakdown_has_completeness_metadata(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    breakdown = final["score_breakdown"]
    assert breakdown is not None
    assert breakdown.recommendation_scope != "UNKNOWN"
    assert breakdown.analysis_completeness_score > 0
    assert len(breakdown.completed_components) > 0
    assert len(breakdown.missing_components) > 0


@pytest.mark.asyncio
async def test_missing_details_includes_news_and_portfolio(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    assert final["neutral_rec"] is not None
    missing = final["neutral_rec"].missing_details
    assert any("M8" in d or "news" in d.lower() for d in missing)
    assert any("M9" in d or "portfolio" in d.lower() for d in missing)


@pytest.mark.asyncio
async def test_fundamentals_snapshot_in_state(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    assert final["fundamentals_snapshot"] is not None
    assert final["fundamentals_data_quality"] > 0
