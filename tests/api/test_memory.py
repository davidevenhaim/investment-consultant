"""API tests for GET /api/v1/memory/{symbol} and POST /api/v1/memory/{symbol}/note."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_memory_no_history(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/memory/AAPL")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["symbol"] == "AAPL"
    assert data["memory_count"] == 0
    assert data["previous_recommendation"] == {}
    assert data["relevant_memories"] == []
    assert "First run" in (data["memory_summary"] or "")


@pytest.mark.asyncio
async def test_get_memory_with_history(api_client: AsyncClient, fake_memory_store) -> None:
    from memory.collections import RECOMMENDATION_REPORTS
    from memory.schemas import MemoryDocument

    doc = MemoryDocument(
        id="rec_run1_AAPL",
        symbol="AAPL",
        document_type="recommendation_report",
        title="AAPL — HOLD",
        content="Symbol: AAPL\nAction: HOLD",
        metadata={
            "symbol": "AAPL",
            "action": "HOLD",
            "score": 60,
            "as_of_time": "2026-05-07T10:00:00+00:00",
            "created_at_ts": 1000,
        },
        created_at=datetime.now(UTC),
    )
    await fake_memory_store.add_document(RECOMMENDATION_REPORTS, doc)

    resp = await api_client.get("/api/v1/memory/AAPL")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["memory_count"] == 1
    assert len(data["relevant_memories"]) == 1
    assert data["relevant_memories"][0]["action"] == "HOLD"


@pytest.mark.asyncio
async def test_get_memory_symbol_uppercased(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/memory/aapl")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_post_note_success(api_client: AsyncClient, fake_memory_store) -> None:
    resp = await api_client.post(
        "/api/v1/memory/AAPL/note",
        json={"title": "Earnings watch", "content": "Watch Q3 EPS closely."},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["symbol"] == "AAPL"
    assert data["title"] == "Earnings watch"
    assert data["doc_id"].startswith("note_AAPL_")

    from memory.collections import MANUAL_NOTES

    assert fake_memory_store.count(MANUAL_NOTES) == 1


@pytest.mark.asyncio
async def test_post_note_empty_title_rejected(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/memory/AAPL/note",
        json={"title": "   ", "content": "Some content"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_post_note_empty_content_rejected(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/memory/AAPL/note",
        json={"title": "Valid title", "content": ""},
    )
    assert resp.status_code == 422
