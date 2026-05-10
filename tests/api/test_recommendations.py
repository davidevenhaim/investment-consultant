"""Recommendation API tests — require DB."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_latest_recommendations_empty(api_client) -> None:
    resp = await api_client.get("/api/v1/recommendations/latest")
    assert resp.status_code == 200
    body = resp.json()
    assert isinstance(body["data"], list)
    assert body["data"] == []


@pytest.mark.asyncio
async def test_latest_recommendations_with_watchlist_no_recs(api_client) -> None:
    await api_client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    await api_client.post("/api/v1/watchlist", json={"symbol": "NVDA"})

    resp = await api_client.get("/api/v1/recommendations/latest")
    assert resp.status_code == 200
    data = resp.json()["data"]
    # Two symbols in watchlist, neutral is None for both (no runs yet)
    symbols = {item["symbol"] for item in data}
    assert {"AAPL", "NVDA"}.issubset(symbols)
    assert all(item["neutral"] is None for item in data)


@pytest.mark.asyncio
async def test_latest_recommendations_includes_score_breakdown_json(api_client: AsyncClient) -> None:
    """After a research run, score_breakdown_json must be present and non-null."""
    await api_client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    run_resp = await api_client.post(
        "/api/v1/research-runs", json={"symbols": ["AAPL"]}
    )
    assert run_resp.status_code == 201

    resp = await api_client.get("/api/v1/recommendations/latest")
    data = resp.json()["data"]
    aapl = next((d for d in data if d["symbol"] == "AAPL"), None)
    assert aapl is not None
    assert aapl["neutral"] is not None
    assert "score_breakdown_json" in aapl["neutral"]
    assert aapl["neutral"]["score_breakdown_json"] is not None


@pytest.mark.asyncio
async def test_score_breakdown_json_llm_disabled_by_default(api_client: AsyncClient) -> None:
    """With LLM_ENABLED=false (default in tests), score_breakdown_json.llm_enabled must be false."""
    await api_client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})

    resp = await api_client.get("/api/v1/recommendations/latest")
    data = resp.json()["data"]
    aapl = next(d for d in data if d["symbol"] == "AAPL")
    bd = aapl["neutral"]["score_breakdown_json"]
    assert bd["llm_enabled"] is False
    assert bd["llm_confidence_penalty"] == 0.0
    assert bd["thesis_alignment"] == "NO_PREVIOUS_THESIS"


@pytest.mark.asyncio
async def test_score_breakdown_json_with_fake_llm_enabled(
    db_session, fake_memory_store
) -> None:
    """With FakeClaudeClient injected, score_breakdown_json.llm_enabled must be true."""
    from unittest.mock import patch

    from ai.fake_client import FakeClaudeClient
    from db.repositories import PromptVersionRepository
    from db.session import get_db
    from httpx import ASGITransport, AsyncClient

    from apps.api.main import app
    from tests.fundamentals.conftest import MockFundamentalsProvider
    from tests.market_data.conftest import MockProvider

    async def override_get_db():
        yield db_session

    # Seed the combined_analysis prompt
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

    fake_llm = FakeClaudeClient()
    mp = MockProvider()
    fp = MockFundamentalsProvider()

    app.dependency_overrides[get_db] = override_get_db
    from news.fake_provider import FakeNewsProvider as FakeNews

    with (
        patch("market_data.service._default_provider", return_value=mp),
        patch("fundamentals.service._default_provider", return_value=fp),
        patch("memory.service._get_default_store", return_value=fake_memory_store),
        patch("news.service._default_provider", return_value=FakeNews()),
        patch("research_graph.runner.build_graph_for_session") as mock_build,
    ):
        # Build graph with fake LLM client
        from research_graph.graph import build_graph_for_session as real_build

        def build_with_llm(session, market_provider=None, fundamentals_provider=None,
                           memory_store=None, llm_client=None, news_provider=None):
            return real_build(
                session,
                market_provider=market_provider,
                fundamentals_provider=fundamentals_provider,
                memory_store=memory_store,
                llm_client=fake_llm,
                news_provider=news_provider,
            )

        mock_build.side_effect = build_with_llm

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            await client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
            await client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})
            resp = await client.get("/api/v1/recommendations/latest")

    app.dependency_overrides.pop(get_db, None)

    data = resp.json()["data"]
    aapl = next(d for d in data if d["symbol"] == "AAPL")
    bd = aapl["neutral"]["score_breakdown_json"]
    assert bd["llm_enabled"] is True
    assert bd["llm_model"] is not None
    assert bd["thesis_alignment"] != ""


@pytest.mark.asyncio
async def test_latest_recommendations_includes_personalized_field(api_client: AsyncClient) -> None:
    await api_client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    run_resp = await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})
    assert run_resp.status_code == 201

    resp = await api_client.get("/api/v1/recommendations/latest")
    data = resp.json()["data"]
    aapl = next(d for d in data if d["symbol"] == "AAPL")
    # personalized field must be present (may be None or dict)
    assert "personalized" in aapl


@pytest.mark.asyncio
async def test_personalized_includes_position_sizing_json(api_client: AsyncClient) -> None:
    await api_client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})

    resp = await api_client.get("/api/v1/recommendations/latest")
    data = resp.json()["data"]
    aapl = next(d for d in data if d["symbol"] == "AAPL")
    if aapl["personalized"] is not None:
        assert "position_sizing_json" in aapl["personalized"]
        assert isinstance(aapl["personalized"]["position_sizing_json"], dict)
