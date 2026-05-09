"""Tests for memory Pydantic schemas."""

from datetime import UTC, datetime

from memory.schemas import MemoryContext, MemoryDocument, MemorySearchResult


def _doc() -> MemoryDocument:
    return MemoryDocument(
        id="rec_run1_AAPL",
        symbol="AAPL",
        document_type="recommendation_report",
        title="AAPL research report — HOLD — score 60 — 2026-05-07",
        content="Symbol: AAPL\nAction: HOLD\nScore: 60/100",
        metadata={"symbol": "AAPL", "action": "HOLD", "score": 60, "created_at_ts": 1000},
        created_at=datetime.now(UTC),
    )


def test_memory_document_round_trip() -> None:
    doc = _doc()
    assert doc.id == "rec_run1_AAPL"
    assert doc.symbol == "AAPL"
    assert doc.metadata["score"] == 60


def test_memory_search_result_defaults() -> None:
    result = MemorySearchResult(
        id="x",
        symbol="AAPL",
        document_type="recommendation_report",
        title="t",
        content="c",
        metadata={},
    )
    assert result.distance is None
    assert result.relevance_score is None


def test_memory_context_defaults() -> None:
    ctx = MemoryContext(symbol="AAPL")
    assert ctx.memory_count == 0
    assert ctx.relevant_memories == []
    assert ctx.previous_recommendation is None
    assert ctx.previous_thesis is None


def test_memory_context_with_results() -> None:
    result = MemorySearchResult(
        id="x",
        symbol="AAPL",
        document_type="recommendation_report",
        title="t",
        content="thesis text",
        metadata={"action": "HOLD", "score": 60},
    )
    ctx = MemoryContext(
        symbol="AAPL",
        previous_recommendation={"action": "HOLD", "score": 60},
        previous_thesis="thesis text",
        relevant_memories=[result],
        memory_summary="Found 1 previous research report for AAPL.",
        memory_count=1,
    )
    assert ctx.memory_count == 1
    assert ctx.previous_recommendation["action"] == "HOLD"
    assert ctx.previous_thesis == "thesis text"
