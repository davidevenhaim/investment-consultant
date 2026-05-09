"""Fundamentals API endpoint tests."""

import pytest


@pytest.mark.asyncio
async def test_fundamentals_404_for_unknown_symbol(api_client) -> None:
    resp = await api_client.get("/api/v1/fundamentals/ZZZZ/latest")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_fundamentals_after_run(api_client) -> None:
    await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})

    resp = await api_client.get("/api/v1/fundamentals/AAPL/latest?provider=mock")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["symbol"] == "AAPL"
    assert data["field_completeness"] > 0
    assert data["as_of_date"] is not None
    assert data["provider"] == "mock"


@pytest.mark.asyncio
async def test_recommendations_have_completeness_metadata(api_client) -> None:
    await api_client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})

    resp = await api_client.get("/api/v1/recommendations/latest")
    assert resp.status_code == 200
    data = resp.json()["data"]
    aapl = next((r for r in data if r["symbol"] == "AAPL"), None)
    assert aapl is not None
    assert aapl["neutral"] is not None
    # final_reason should mention real data and stubs
    assert "real" in aapl["neutral"]["final_reason"].lower()
    # price_at_recommendation should be set
    assert aapl["neutral"]["price_at_recommendation"] is not None


@pytest.mark.asyncio
async def test_run_completes_with_fundamentals(api_client) -> None:
    resp = await api_client.post(
        "/api/v1/research-runs",
        json={"run_type": "MANUAL", "symbols": ["AAPL", "NVDA"]},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["status"] == "COMPLETED"
    assert len(data["tickers"]) == 2
    assert all(t["status"] == "COMPLETED" for t in data["tickers"])
