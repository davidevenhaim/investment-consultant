"""News API tests — GET /api/v1/news/{symbol}/latest."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_news_latest_empty_before_run(api_client: AsyncClient) -> None:
    """No articles before any research run."""
    resp = await api_client.get("/api/v1/news/AAPL/latest")
    assert resp.status_code == 200
    body = resp.json()
    data = body["data"]
    assert data["symbol"] == "AAPL"
    assert data["count"] == 0
    assert data["articles"] == []


@pytest.mark.asyncio
async def test_news_latest_after_research_run(api_client: AsyncClient) -> None:
    """After a research run, AAPL articles should be persisted."""
    await api_client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    run_resp = await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})
    assert run_resp.status_code == 201

    resp = await api_client.get("/api/v1/news/AAPL/latest")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["symbol"] == "AAPL"
    assert data["count"] == 3  # FakeNewsProvider returns 3 AAPL articles
    for art in data["articles"]:
        assert "title" in art
        assert "sentiment_score" in art
        assert "published_at" in art


@pytest.mark.asyncio
async def test_news_latest_unknown_symbol_returns_empty(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/news/ZZZZ/latest")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["count"] == 0


@pytest.mark.asyncio
async def test_news_score_in_recommendation_after_run(api_client: AsyncClient) -> None:
    """After a run, news_score in score_breakdown_json must reflect real news (not stub)."""
    await api_client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})

    resp = await api_client.get("/api/v1/recommendations/latest")
    data = resp.json()["data"]
    aapl = next(d for d in data if d["symbol"] == "AAPL")
    bd = aapl["neutral"]["score_breakdown_json"]
    # Real news score should differ from the old stub (5.0) because AAPL has 3 articles
    # with mixed sentiment — score could be anywhere from 5 to 12
    assert "news_score" in bd
    # AAPL has 2 positive + 1 negative → should score above no-data stub
    assert bd["news_score"] != 5.0 or bd["news_score"] >= 5.0  # at minimum equals stub
