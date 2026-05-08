"""Market data API endpoint tests."""
import pytest


@pytest.mark.asyncio
async def test_market_data_404_for_unknown_symbol(api_client) -> None:
    resp = await api_client.get("/api/v1/market-data/ZZZZ/latest")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_market_data_latest_after_run(api_client) -> None:
    # Run research to populate market_prices
    await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})

    resp = await api_client.get("/api/v1/market-data/AAPL/latest?provider=mock")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["symbol"] == "AAPL"
    assert data["bar_count"] > 0
    assert data["latest_close"] is not None
    assert data["latest_price_date"] is not None
    assert data["provider"] == "mock"


@pytest.mark.asyncio
async def test_recommendations_have_price_at_recommendation(api_client) -> None:
    await api_client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})

    resp = await api_client.get("/api/v1/recommendations/latest")
    assert resp.status_code == 200
    data = resp.json()["data"]
    aapl = next((r for r in data if r["symbol"] == "AAPL"), None)
    assert aapl is not None
    assert aapl["neutral"] is not None
    assert aapl["neutral"]["price_at_recommendation"] is not None
    assert float(aapl["neutral"]["price_at_recommendation"]) > 0
