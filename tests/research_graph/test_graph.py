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
from tests.memory.fake_store import FakeMemoryStore


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


@pytest.fixture
def mem_store() -> FakeMemoryStore:
    return FakeMemoryStore()


def _graph(
    session: AsyncSession,
    mp: MockProvider,
    fp: MockFundamentalsProvider,
    ms: FakeMemoryStore | None = None,
) -> object:
    from news.fake_provider import FakeNewsProvider

    return build_graph_for_session(
        session,
        market_provider=mp,
        fundamentals_provider=fp,
        memory_store=ms or FakeMemoryStore(),
        news_provider=FakeNewsProvider(),
    )


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
    mem_store: FakeMemoryStore,
) -> None:
    repo = ResearchRunRepository(db_session)
    run = await repo.create(run_type=ResearchRunType.MANUAL)
    tickers = await repo.add_tickers(run.id, ["AAPL", "NVDA", "TSLA"])

    summary = await run_research_for_run(
        run,
        tickers,
        db_session,
        "v0.1.0",
        market_provider=market_provider,
        fundamentals_provider=fund_provider,
        memory_store=mem_store,
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
    # M9: FakeNewsProvider is injected, so news is available → in completed, not missing
    assert "news" in final["completed_components"]
    # M9: No portfolio seeded in test DB → portfolio_context stays in missing
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
    # M9: FakeNewsProvider provides real news, so news is no longer in missing_details.
    # Portfolio context is missing (no portfolio seeded) → should appear.
    assert any("portfolio" in d.lower() for d in missing)


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


@pytest.mark.asyncio
async def test_memory_context_populated_after_run(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
    mem_store: FakeMemoryStore,
) -> None:
    """First run: memory_count=0. Second run: memory_count=1."""
    run1, ticker1 = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider, mem_store)
    final1 = await graph.ainvoke(make_initial_state(run1, ticker1, "v0.1.0"))

    # First run has no prior memory
    assert final1["memory_count"] == 0
    assert "First run" in (final1["memory_summary"] or "")

    # After first run, Chroma should have the document
    from memory.collections import RECOMMENDATION_REPORTS

    assert mem_store.count(RECOMMENDATION_REPORTS) == 1

    # Second run should retrieve the first run's memory
    run2, ticker2 = await _make_run_and_ticker(db_session, "AAPL")
    final2 = await graph.ainvoke(make_initial_state(run2, ticker2, "v0.1.0"))
    assert final2["memory_count"] == 1
    assert final2["previous_thesis"] is not None


@pytest.mark.asyncio
async def test_chroma_failure_does_not_crash_run(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    """Chroma failure must never crash the research run."""
    from typing import Any

    from core.errors import MemoryStoreError
    from memory.interfaces import MemoryStore
    from memory.schemas import MemoryDocument, MemorySearchResult

    class AlwaysFailStore(MemoryStore):
        async def add_document(self, collection: str, doc: MemoryDocument) -> None:
            raise MemoryStoreError("Chroma down", {})

        async def query_documents(
            self, collection: str, query_text: str, filters: dict[str, Any], limit: int = 5
        ) -> list[MemorySearchResult]:
            raise MemoryStoreError("Chroma down", {})

    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = build_graph_for_session(
        db_session,
        market_provider=market_provider,
        fundamentals_provider=fund_provider,
        memory_store=AlwaysFailStore(),
    )
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    # Run completes successfully despite Chroma being down
    assert final["neutral_rec"] is not None
    assert final["memory_count"] == 0


# ── M7 LLM graph tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_graph_with_fake_llm_client(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
    mem_store: FakeMemoryStore,
) -> None:
    """Full graph with FakeClaudeClient completes; LLM analysis written to state."""
    from ai.fake_client import FakeClaudeClient
    from db.repositories import PromptVersionRepository

    # Seed the combined_analysis prompt version
    pv_repo = PromptVersionRepository(db_session)
    existing = await pv_repo.get_active("combined_analysis")
    if existing is None:
        await pv_repo.create(
            name="combined_analysis",
            version="v0.1.0",
            prompt_text="Analyze {{SYMBOL}}.\n{{CONTEXT}}",
            is_active=True,
        )
        await db_session.flush()

    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = build_graph_for_session(
        db_session,
        market_provider=market_provider,
        fundamentals_provider=fund_provider,
        memory_store=mem_store,
        llm_client=FakeClaudeClient(),
    )
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    assert final["neutral_rec"] is not None
    assert final["llm_analysis"] is not None
    assert final["llm_analysis"].llm_enabled is True


@pytest.mark.asyncio
async def test_full_graph_with_llm_disabled(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
    mem_store: FakeMemoryStore,
) -> None:
    """LLM disabled (no client, LLM_ENABLED=false from conftest): graph completes."""
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    # conftest autouse sets LLM_ENABLED=false — no explicit patch needed
    graph = build_graph_for_session(
        db_session,
        market_provider=market_provider,
        fundamentals_provider=fund_provider,
        memory_store=mem_store,
        llm_client=None,
    )
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    assert final["neutral_rec"] is not None
    assert final["llm_analysis"].llm_enabled is False
    assert final["score_breakdown"].llm_enabled is False


@pytest.mark.asyncio
async def test_full_graph_with_failing_llm_completes(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
    mem_store: FakeMemoryStore,
) -> None:
    """Failing LLM client: run completes, empty analysis, warning recorded."""
    from ai.fake_client import FakeClaudeClient
    from db.repositories import PromptVersionRepository

    pv_repo = PromptVersionRepository(db_session)
    existing = await pv_repo.get_active("combined_analysis")
    if existing is None:
        await pv_repo.create(
            name="combined_analysis",
            version="v0.1.0",
            prompt_text="Analyze {{SYMBOL}}.\n{{CONTEXT}}",
            is_active=True,
        )
        await db_session.flush()

    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = build_graph_for_session(
        db_session,
        market_provider=market_provider,
        fundamentals_provider=fund_provider,
        memory_store=mem_store,
        llm_client=FakeClaudeClient(fail=True),
    )
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    assert final["neutral_rec"] is not None
    assert final["llm_analysis"].llm_enabled is False
    assert len(final.get("llm_warnings", [])) > 0


@pytest.mark.asyncio
async def test_score_breakdown_json_has_llm_metadata_when_llm_ran(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
    mem_store: FakeMemoryStore,
) -> None:
    from ai.fake_client import FakeClaudeClient
    from db.repositories import PromptVersionRepository
    from sqlalchemy import select

    pv_repo = PromptVersionRepository(db_session)
    existing = await pv_repo.get_active("combined_analysis")
    if existing is None:
        await pv_repo.create(
            name="combined_analysis",
            version="v0.1.0",
            prompt_text="Analyze {{SYMBOL}}.\n{{CONTEXT}}",
            is_active=True,
        )
        await db_session.flush()

    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = build_graph_for_session(
        db_session,
        market_provider=market_provider,
        fundamentals_provider=fund_provider,
        memory_store=mem_store,
        llm_client=FakeClaudeClient(),
    )
    await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    from db.models import NeutralRecommendation as NeutralRecM

    result = await db_session.execute(
        select(NeutralRecM).where(NeutralRecM.research_run_id == run.id)
    )
    rec = result.scalar_one()
    bd = rec.score_breakdown_json
    assert bd.get("llm_enabled") is True
    assert bd.get("llm_model") is not None


@pytest.mark.asyncio
async def test_evidence_row_created_when_llm_ran(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
    mem_store: FakeMemoryStore,
) -> None:
    from ai.fake_client import FakeClaudeClient
    from db.models import RecommendationEvidence
    from db.repositories import PromptVersionRepository
    from sqlalchemy import select

    pv_repo = PromptVersionRepository(db_session)
    existing = await pv_repo.get_active("combined_analysis")
    if existing is None:
        await pv_repo.create(
            name="combined_analysis",
            version="v0.1.0",
            prompt_text="Analyze {{SYMBOL}}.\n{{CONTEXT}}",
            is_active=True,
        )
        await db_session.flush()

    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = build_graph_for_session(
        db_session,
        market_provider=market_provider,
        fundamentals_provider=fund_provider,
        memory_store=mem_store,
        llm_client=FakeClaudeClient(),
    )
    await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    from db.models import NeutralRecommendation as NeutralRecM

    nr_result = await db_session.execute(
        select(NeutralRecM).where(NeutralRecM.research_run_id == run.id)
    )
    nr = nr_result.scalar_one()

    ev_result = await db_session.execute(
        select(RecommendationEvidence).where(
            RecommendationEvidence.recommendation_id == nr.id,
            RecommendationEvidence.evidence_type == "LLM_ANALYSIS",
        )
    )
    evidence = ev_result.scalar_one_or_none()
    assert evidence is not None
    assert evidence.source.startswith("claude/")
    assert evidence.payload_json.get("llm_enabled") is True


@pytest.mark.asyncio
async def test_no_evidence_row_when_llm_disabled(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
    mem_store: FakeMemoryStore,
) -> None:
    from db.models import NeutralRecommendation as NeutralRecM
    from db.models import RecommendationEvidence
    from sqlalchemy import select

    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = build_graph_for_session(
        db_session,
        market_provider=market_provider,
        fundamentals_provider=fund_provider,
        memory_store=mem_store,
        llm_client=None,
    )
    # conftest autouse sets LLM_ENABLED=false — no explicit patch needed
    await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    nr_result = await db_session.execute(
        select(NeutralRecM).where(NeutralRecM.research_run_id == run.id)
    )
    nr = nr_result.scalar_one()
    ev_result = await db_session.execute(
        select(RecommendationEvidence).where(
            RecommendationEvidence.recommendation_id == nr.id,
            RecommendationEvidence.evidence_type == "LLM_ANALYSIS",
        )
    )
    evidence = ev_result.scalar_one_or_none()
    assert evidence is None


@pytest.mark.asyncio
async def test_full_graph_personalized_has_position_sizing(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    pers = final.get("personalized_rec")
    assert pers is not None
    # suggested_trade_json should always be a dict (may be NONE type)
    assert pers.suggested_trade_json is not None
    assert "trade_type" in pers.suggested_trade_json


@pytest.mark.asyncio
async def test_full_graph_no_errors_with_news_provider(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    """Graph runs cleanly with FakeNewsProvider."""
    run, ticker = await _make_run_and_ticker(db_session, "NVDA")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))
    assert final["errors"] == []
    assert final["neutral_rec"] is not None


@pytest.mark.asyncio
async def test_full_graph_portfolio_context_optional(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    """Graph runs without portfolio (no account seeded) — degrades gracefully."""
    run, ticker = await _make_run_and_ticker(db_session, "TSLA")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))
    # No portfolio seeded in test DB — portfolio_context should be None
    assert final.get("portfolio_context") is None
    # But graph still produces recommendations
    assert final["neutral_rec"] is not None
    assert final["personalized_rec"] is not None
    assert final["errors"] == []


# ── M9 portfolio metadata fix (score_breakdown completeness) ──────────────────


async def _seed_portfolio(session: AsyncSession, symbol: str, quantity: float = 10.0) -> None:
    """Seed a default portfolio account + position for testing."""
    from db.repositories import PortfolioPositionRepository
    from portfolio.service import ensure_default_portfolio

    account = await ensure_default_portfolio(session)
    pos_repo = PortfolioPositionRepository(session)
    await pos_repo.upsert_position(
        account_id=account.id,
        symbol=symbol,
        quantity=quantity,
        average_cost=150.0,
    )
    await session.flush()


@pytest.mark.asyncio
async def test_portfolio_context_in_completed_when_portfolio_seeded(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    """When portfolio is seeded, score_breakdown.completed_components includes portfolio_context."""
    await _seed_portfolio(db_session, "AAPL")
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    breakdown = final["neutral_rec"].score_breakdown
    assert "portfolio_context" in breakdown.completed_components
    assert "portfolio_context" not in breakdown.missing_components


@pytest.mark.asyncio
async def test_portfolio_context_quality_score_one_when_seeded(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    """When portfolio found, component_quality_scores['portfolio_context'] == 1.0."""
    await _seed_portfolio(db_session, "AAPL")
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    breakdown = final["neutral_rec"].score_breakdown
    assert breakdown.component_quality_scores.get("portfolio_context") == 1.0


@pytest.mark.asyncio
async def test_portfolio_completeness_increases_when_portfolio_seeded(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    """analysis_completeness_score is higher when portfolio is available vs not."""
    # Run without portfolio to get baseline
    run_no, ticker_no = await _make_run_and_ticker(db_session, "NVDA")
    final_no = await _graph(db_session, market_provider, fund_provider).ainvoke(
        make_initial_state(run_no, ticker_no, "v0.1.0")
    )
    completeness_no_portfolio = final_no["neutral_rec"].score_breakdown.analysis_completeness_score

    # Seed portfolio, run again
    await _seed_portfolio(db_session, "NVDA")
    run_yes, ticker_yes = await _make_run_and_ticker(db_session, "NVDA")
    final_yes = await _graph(db_session, market_provider, fund_provider).ainvoke(
        make_initial_state(run_yes, ticker_yes, "v0.1.0")
    )
    completeness_with_portfolio = final_yes[
        "neutral_rec"
    ].score_breakdown.analysis_completeness_score

    assert completeness_with_portfolio > completeness_no_portfolio


@pytest.mark.asyncio
async def test_score_breakdown_json_persisted_has_portfolio_in_completed(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    """score_breakdown_json in DB reflects portfolio_context in completed_components."""
    from sqlalchemy import select

    await _seed_portfolio(db_session, "AAPL")
    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))

    from db.models import NeutralRecommendation as NeutralRecM

    result = await db_session.execute(
        select(NeutralRecM).where(NeutralRecM.research_run_id == run.id)
    )
    rec = result.scalar_one()
    bd = rec.score_breakdown_json
    assert "portfolio_context" in bd.get("completed_components", [])
    assert "portfolio_context" not in bd.get("missing_components", [])
    assert bd.get("component_quality_scores", {}).get("portfolio_context") == 1.0


@pytest.mark.asyncio
async def test_full_graph_uses_broker_scoped_symbol_trading_stats(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
) -> None:
    """Graph state and persisted personalized rec include broker-scoped symbol stats."""
    import datetime as dt

    from db.models import BrokerAccount, ManualTrade
    from db.models import PersonalizedRecommendation as PersonalizedRecM

    broker_account = BrokerAccount(
        provider="IBKR",
        display_name="Graph Test Broker",
        connection_mode="LOCAL_TWS",
        client_id=1,
        readonly=True,
        is_active=True,
        metadata_json={},
    )
    db_session.add(broker_account)
    await db_session.flush()

    now = dt.datetime.now(dt.UTC)
    db_session.add_all(
        [
            ManualTrade(
                broker_account_id=broker_account.id,
                symbol="AAPL",
                side="BUY",
                quantity=10,
                price=150,
                executed_at=now - dt.timedelta(days=180),
                source="manual",
            ),
            ManualTrade(
                broker_account_id=broker_account.id,
                symbol="AAPL",
                side="SELL",
                quantity=10,
                price=180,
                executed_at=now - dt.timedelta(days=30),
                source="manual",
            ),
        ]
    )
    await db_session.flush()

    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider)
    final = await graph.ainvoke(
        make_initial_state(run, ticker, "v0.1.0", broker_account_id=broker_account.id)
    )

    stats = final["symbol_trading_stats"]
    assert stats
    assert stats["executions"] == 2
    assert stats["completed_trades"] == 1
    assert stats["win_rate"] == pytest.approx(1.0)

    result = await db_session.execute(
        select(PersonalizedRecM)
        .join(NeutralRecModel, PersonalizedRecM.neutral_recommendation_id == NeutralRecModel.id)
        .where(NeutralRecModel.research_run_id == run.id)
    )
    personalized = result.scalar_one()
    assert personalized.symbol_trading_stats_json == stats


@pytest.mark.asyncio
async def test_enforce_broker_scope_true_skips_unscoped_trades(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
    mem_store: FakeMemoryStore,
) -> None:
    """M10.3: API-style scoped runs must not merge rows with NULL broker_account_id."""
    import datetime as dt

    from db.models import ManualTrade

    now = dt.datetime.now(dt.UTC)
    db_session.add_all(
        [
            ManualTrade(
                broker_account_id=None,
                symbol="AAPL",
                side="BUY",
                quantity=10,
                price=150,
                executed_at=now - dt.timedelta(days=120),
                source="manual",
            ),
            ManualTrade(
                broker_account_id=None,
                symbol="AAPL",
                side="SELL",
                quantity=10,
                price=180,
                executed_at=now - dt.timedelta(days=30),
                source="manual",
            ),
        ]
    )
    await db_session.flush()

    run, ticker = await _make_run_and_ticker(db_session, "AAPL")
    graph = _graph(db_session, market_provider, fund_provider, mem_store)
    final = await graph.ainvoke(
        make_initial_state(run, ticker, "v0.1.0", enforce_broker_scope=True)
    )
    assert not final.get("symbol_trading_stats")


@pytest.mark.asyncio
async def test_enforce_broker_scope_false_loads_unscoped_trades(
    db_session: AsyncSession,
    market_provider: MockProvider,
    fund_provider: MockFundamentalsProvider,
    mem_store: FakeMemoryStore,
) -> None:
    """Legacy graph callers (enforce_broker_scope=False) still see global unscoped trades."""
    import datetime as dt

    from db.models import ManualTrade

    now = dt.datetime.now(dt.UTC)
    db_session.add_all(
        [
            ManualTrade(
                broker_account_id=None,
                symbol="MSFT",
                side="BUY",
                quantity=5,
                price=300,
                executed_at=now - dt.timedelta(days=100),
                source="manual",
            ),
            ManualTrade(
                broker_account_id=None,
                symbol="MSFT",
                side="SELL",
                quantity=5,
                price=330,
                executed_at=now - dt.timedelta(days=20),
                source="manual",
            ),
        ]
    )
    await db_session.flush()

    run, ticker = await _make_run_and_ticker(db_session, "MSFT")
    graph = _graph(db_session, market_provider, fund_provider, mem_store)
    final = await graph.ainvoke(make_initial_state(run, ticker, "v0.1.0"))
    stats = final.get("symbol_trading_stats") or {}
    assert stats.get("executions") == 2
    assert stats.get("completed_trades") == 1
