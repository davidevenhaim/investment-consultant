"""Integration tests against a live ChromaDB instance. Excluded from make test.

Run manually:
    make test-integration
    # or
    pytest tests/integration/ -m integration -v

Each test uses isolated collection names (prefixed with "int_test_") and cleans
up after itself. Real app collections (recommendation_reports etc.) are never touched.
"""

import pytest
from memory.chroma_client import ChromaMemoryStore

pytestmark = pytest.mark.integration

# Dedicated test-only collection — never the real production collection
_TEST_COLLECTION = "int_test_recommendation_reports"


@pytest.fixture
async def chroma_store():
    """Live ChromaDB store; creates test collection, yields, deletes it."""
    import contextlib

    store = ChromaMemoryStore(host="localhost", port=8001)
    client = await store._get_client()
    with contextlib.suppress(Exception):
        await client.delete_collection(_TEST_COLLECTION)
    await client.get_or_create_collection(_TEST_COLLECTION)
    yield store
    with contextlib.suppress(Exception):
        await client.delete_collection(_TEST_COLLECTION)


@pytest.mark.asyncio
async def test_chroma_add_and_query(chroma_store: ChromaMemoryStore) -> None:
    """Round-trip: add a document, query it back."""
    from datetime import UTC, datetime

    from memory.schemas import MemoryDocument

    doc = MemoryDocument(
        id="int_test_doc_AAPL",
        symbol="AAPL",
        document_type="recommendation_report",
        title="AAPL integration test",
        content="Symbol: AAPL\nAction: HOLD\nScore: 60/100",
        metadata={
            "symbol": "AAPL",
            "document_type": "recommendation_report",
            "action": "HOLD",
            "research_run_id": "int-test-run-001",
            "score": 60,
            "created_at_ts": int(datetime.now(UTC).timestamp()),
        },
        created_at=datetime.now(UTC),
    )
    await chroma_store.add_document(_TEST_COLLECTION, doc)

    results = await chroma_store.query_documents(
        collection=_TEST_COLLECTION,
        query_text="AAPL recommendation",
        filters={"symbol": "AAPL"},
        limit=5,
    )
    assert len(results) >= 1
    assert any(r.id == "int_test_doc_AAPL" for r in results)


@pytest.mark.asyncio
async def test_chroma_symbol_isolation(chroma_store: ChromaMemoryStore) -> None:
    """Documents for NVDA must not appear in AAPL queries."""
    from datetime import UTC, datetime

    from memory.schemas import MemoryDocument

    nvda_doc = MemoryDocument(
        id="int_test_doc_NVDA",
        symbol="NVDA",
        document_type="recommendation_report",
        title="NVDA integration test",
        content="Symbol: NVDA\nAction: BUY_CANDIDATE",
        metadata={
            "symbol": "NVDA",
            "document_type": "recommendation_report",
            "action": "BUY_CANDIDATE",
            "research_run_id": "int-test-run-002",
            "score": 75,
            "created_at_ts": int(datetime.now(UTC).timestamp()),
        },
        created_at=datetime.now(UTC),
    )
    await chroma_store.add_document(_TEST_COLLECTION, nvda_doc)

    results = await chroma_store.query_documents(
        collection=_TEST_COLLECTION,
        query_text="AAPL recommendation",
        filters={"symbol": "AAPL"},
        limit=5,
    )
    for r in results:
        assert r.symbol == "AAPL", f"Cross-symbol contamination: got {r.symbol}"


@pytest.mark.asyncio
async def test_chroma_recency_ordering(chroma_store: ChromaMemoryStore) -> None:
    """Most recent doc (highest created_at_ts) must appear first."""
    from datetime import UTC, datetime

    from memory.schemas import MemoryDocument

    base_ts = int(datetime.now(UTC).timestamp())
    for i, ts_offset in enumerate([0, 100, 200]):
        doc = MemoryDocument(
            id=f"int_test_order_{i}",
            symbol="AAPL",
            document_type="recommendation_report",
            title=f"AAPL run {i}",
            content=f"Symbol: AAPL\nRun: {i}",
            metadata={
                "symbol": "AAPL",
                "document_type": "recommendation_report",
                "action": "HOLD",
                "research_run_id": f"int-test-run-order-{i}",
                "score": 60,
                "created_at_ts": base_ts + ts_offset,
            },
            created_at=datetime.now(UTC),
        )
        await chroma_store.add_document(_TEST_COLLECTION, doc)

    results = await chroma_store.query_documents(
        collection=_TEST_COLLECTION,
        query_text="AAPL recommendation",
        filters={"symbol": "AAPL"},
        limit=5,
    )
    assert len(results) == 3
    # Most recent first
    assert results[0].metadata["created_at_ts"] >= results[1].metadata["created_at_ts"]
    assert results[1].metadata["created_at_ts"] >= results[2].metadata["created_at_ts"]


@pytest.mark.asyncio
async def test_chroma_upsert_is_idempotent(chroma_store: ChromaMemoryStore) -> None:
    """Upserting the same doc_id twice must not duplicate."""
    from datetime import UTC, datetime

    from memory.schemas import MemoryDocument

    def _doc(score: int) -> MemoryDocument:
        return MemoryDocument(
            id="int_test_upsert_AAPL",
            symbol="AAPL",
            document_type="recommendation_report",
            title="upsert test",
            content=f"Score: {score}/100",
            metadata={
                "symbol": "AAPL",
                "action": "HOLD",
                "research_run_id": "int-run-upsert",
                "score": score,
                "created_at_ts": int(datetime.now(UTC).timestamp()),
            },
            created_at=datetime.now(UTC),
        )

    await chroma_store.add_document(_TEST_COLLECTION, _doc(60))
    await chroma_store.add_document(_TEST_COLLECTION, _doc(75))  # upsert

    results = await chroma_store.query_documents(
        collection=_TEST_COLLECTION,
        query_text="AAPL",
        filters={"symbol": "AAPL"},
        limit=10,
    )
    assert len(results) == 1
    assert results[0].metadata["score"] == 75  # updated value
