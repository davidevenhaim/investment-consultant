"""Recommendation API tests — require DB."""
import pytest


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
