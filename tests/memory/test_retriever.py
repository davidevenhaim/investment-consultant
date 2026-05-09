"""Tests for retrieve_symbol_memory — logic, summary string, failure handling."""

from datetime import UTC, datetime

import pytest
from memory.collections import RECOMMENDATION_REPORTS
from memory.retriever import retrieve_symbol_memory
from memory.schemas import MemoryContext, MemoryDocument, MemorySearchResult

from tests.memory.fake_store import FakeMemoryStore


def _search_result(
    symbol: str = "AAPL",
    action: str = "HOLD",
    score: int = 60,
    price: float = 190.0,
    as_of_time: str = "2026-05-07T10:00:00+00:00",
    created_at_ts: int = 1000,
) -> MemorySearchResult:
    return MemorySearchResult(
        id=f"rec_run1_{symbol}",
        symbol=symbol,
        document_type="recommendation_report",
        title=f"{symbol} — {action}",
        content=f"Symbol: {symbol}\nAction: {action}",
        metadata={
            "symbol": symbol,
            "action": action,
            "personal_action": action,
            "score": score,
            "confidence": 0.75,
            "price_at_recommendation": price,
            "as_of_time": as_of_time,
            "research_run_id": "run-001",
            "created_at_ts": created_at_ts,
        },
        distance=0.1,
        relevance_score=0.9,
    )


@pytest.mark.asyncio
async def test_first_run_returns_empty_context() -> None:
    store = FakeMemoryStore()
    ctx = await retrieve_symbol_memory("AAPL", limit=5, store=store)
    assert isinstance(ctx, MemoryContext)
    assert ctx.memory_count == 0
    assert ctx.previous_recommendation is None
    assert ctx.previous_thesis is None
    assert "First run" in (ctx.memory_summary or "")


@pytest.mark.asyncio
async def test_retrieves_previous_recommendation() -> None:
    store = FakeMemoryStore()
    doc = MemoryDocument(
        id="rec_run1_AAPL",
        symbol="AAPL",
        document_type="recommendation_report",
        title="AAPL — HOLD",
        content="Symbol: AAPL\nAction: HOLD",
        metadata={
            "symbol": "AAPL",
            "action": "HOLD",
            "personal_action": "HOLD",
            "score": 60,
            "confidence": 0.75,
            "price_at_recommendation": 190.0,
            "as_of_time": "2026-05-07T10:00:00+00:00",
            "research_run_id": "run-001",  # required for previous_recommendation
            "created_at_ts": 1000,
        },
        created_at=datetime.now(UTC),
    )
    await store.add_document(RECOMMENDATION_REPORTS, doc)

    ctx = await retrieve_symbol_memory("AAPL", limit=5, store=store)
    assert ctx.memory_count == 1
    assert ctx.previous_recommendation is not None
    assert ctx.previous_recommendation["action"] == "HOLD"
    assert ctx.previous_recommendation["score"] == 60
    assert ctx.previous_thesis is not None
    assert "AAPL" in ctx.previous_thesis


@pytest.mark.asyncio
async def test_memory_summary_single_report() -> None:
    store = FakeMemoryStore()
    doc = MemoryDocument(
        id="rec_run1_AAPL",
        symbol="AAPL",
        document_type="recommendation_report",
        title="t",
        content="c",
        metadata={
            "symbol": "AAPL",
            "action": "BUY_CANDIDATE",
            "research_run_id": "run-summary-001",
            "score": 75,
            "price_at_recommendation": 200.0,
            "as_of_time": "2026-05-07T10:00:00+00:00",
            "created_at_ts": 2000,
        },
        created_at=datetime.now(UTC),
    )
    await store.add_document(RECOMMENDATION_REPORTS, doc)
    ctx = await retrieve_symbol_memory("AAPL", limit=5, store=store)
    summary = ctx.memory_summary or ""
    assert "1 previous research report" in summary
    assert "BUY_CANDIDATE" in summary
    assert "75" in summary
    assert "2026-05-07" in summary


@pytest.mark.asyncio
async def test_memory_summary_multiple_reports() -> None:
    store = FakeMemoryStore()
    for i, ts in enumerate([1000, 2000, 3000]):
        doc = MemoryDocument(
            id=f"rec_run{i}_AAPL",
            symbol="AAPL",
            document_type="recommendation_report",
            title="t",
            content="c",
            metadata={
                "symbol": "AAPL",
                "action": "HOLD",
                "research_run_id": f"run-multi-{i:03d}",
                "score": 60,
                "as_of_time": "2026-05-07T10:00:00+00:00",
                "created_at_ts": ts,
            },
            created_at=datetime.now(UTC),
        )
        await store.add_document(RECOMMENDATION_REPORTS, doc)
    ctx = await retrieve_symbol_memory("AAPL", limit=5, store=store)
    assert ctx.memory_count == 3
    assert "3 previous research reports" in (ctx.memory_summary or "")


@pytest.mark.asyncio
async def test_symbol_filter_isolation() -> None:
    """Retriever must never return results from other symbols."""
    store = FakeMemoryStore()
    for sym in ("AAPL", "NVDA", "TSLA"):
        doc = MemoryDocument(
            id=f"rec_run1_{sym}",
            symbol=sym,
            document_type="recommendation_report",
            title=f"{sym}",
            content=f"Symbol: {sym}",
            metadata={"symbol": sym, "action": "HOLD", "research_run_id": f"run-{sym}", "created_at_ts": 1000},
            created_at=datetime.now(UTC),
        )
        await store.add_document(RECOMMENDATION_REPORTS, doc)

    ctx = await retrieve_symbol_memory("AAPL", limit=5, store=store)
    assert ctx.memory_count == 1
    for r in ctx.relevant_memories:
        assert r.symbol == "AAPL"


@pytest.mark.asyncio
async def test_store_error_returns_empty_context() -> None:
    from typing import Any

    from core.errors import MemoryStoreError
    from memory.interfaces import MemoryStore
    from memory.schemas import MemoryDocument, MemorySearchResult

    class FailingStore(MemoryStore):
        async def add_document(self, collection: str, doc: MemoryDocument) -> None:
            raise MemoryStoreError("DB down", {})

        async def query_documents(
            self, collection: str, query_text: str, filters: dict[str, Any], limit: int = 5
        ) -> list[MemorySearchResult]:
            raise MemoryStoreError("DB down", {})

    ctx = await retrieve_symbol_memory("AAPL", limit=5, store=FailingStore())
    assert ctx.memory_count == 0
    assert "failed" in (ctx.memory_summary or "").lower()


@pytest.mark.asyncio
async def test_limit_respected() -> None:
    store = FakeMemoryStore()
    for i in range(10):
        doc = MemoryDocument(
            id=f"rec_run{i}_AAPL",
            symbol="AAPL",
            document_type="recommendation_report",
            title="t",
            content="c",
            metadata={"symbol": "AAPL", "created_at_ts": i},
            created_at=datetime.now(UTC),
        )
        await store.add_document(RECOMMENDATION_REPORTS, doc)
    ctx = await retrieve_symbol_memory("AAPL", limit=3, store=store)
    assert ctx.memory_count == 3
    assert len(ctx.relevant_memories) == 3


@pytest.mark.asyncio
async def test_previous_recommendation_skips_docs_without_research_run_id() -> None:
    """
    A doc with action but no research_run_id (e.g. integration test doc) must not
    be used as previous_recommendation. The retriever must use the real research doc.
    """
    store = FakeMemoryStore()

    # Integration test doc — has action but no research_run_id; more recent ts
    test_doc = MemoryDocument(
        id="int_test_doc_AAPL",
        symbol="AAPL",
        document_type="recommendation_report",
        title="integration test",
        content="test content",
        metadata={
            "symbol": "AAPL",
            "action": "HOLD",
            "score": 42,
            "created_at_ts": 9999,  # more recent than real doc
            # no research_run_id
        },
        created_at=datetime.now(UTC),
    )
    # Real research doc — has research_run_id; older ts
    real_doc = MemoryDocument(
        id="rec_real_run_AAPL",
        symbol="AAPL",
        document_type="recommendation_report",
        title="real research",
        content="real thesis content",
        metadata={
            "symbol": "AAPL",
            "action": "BUY_CANDIDATE",
            "research_run_id": "real-run-uuid-001",
            "score": 75,
            "created_at_ts": 5000,
        },
        created_at=datetime.now(UTC),
    )
    await store.add_document(RECOMMENDATION_REPORTS, test_doc)
    await store.add_document(RECOMMENDATION_REPORTS, real_doc)

    ctx = await retrieve_symbol_memory("AAPL", limit=5, store=store)

    # Both docs counted in memory_count
    assert ctx.memory_count == 2

    # But previous_recommendation must come from the real research doc
    assert ctx.previous_recommendation is not None
    assert ctx.previous_recommendation["action"] == "BUY_CANDIDATE"
    assert ctx.previous_recommendation["research_run_id"] == "real-run-uuid-001"

    # previous_thesis is the content of the real doc
    assert ctx.previous_thesis == "real thesis content"


@pytest.mark.asyncio
async def test_previous_recommendation_uses_most_recent_real_doc() -> None:
    """When multiple real research docs exist, newest one (highest created_at_ts) wins."""
    store = FakeMemoryStore()

    for i, (ts, action) in enumerate([(1000, "HOLD"), (2000, "BUY_CANDIDATE"), (3000, "HOLD")]):
        doc = MemoryDocument(
            id=f"rec_run{i}_AAPL",
            symbol="AAPL",
            document_type="recommendation_report",
            title="t",
            content=f"content_{i}",
            metadata={
                "symbol": "AAPL",
                "action": action,
                "research_run_id": f"run-{i:03d}",
                "score": 60 + i * 5,
                "created_at_ts": ts,
            },
            created_at=datetime.now(UTC),
        )
        await store.add_document(RECOMMENDATION_REPORTS, doc)

    ctx = await retrieve_symbol_memory("AAPL", limit=5, store=store)
    assert ctx.memory_count == 3
    # Most recent (ts=3000, action=HOLD) must be used
    assert ctx.previous_recommendation is not None
    assert ctx.previous_recommendation["research_run_id"] == "run-002"
