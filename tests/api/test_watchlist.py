"""Watchlist CRUD API tests — require DB."""

import pytest


@pytest.mark.asyncio
async def test_list_watchlist_empty(api_client) -> None:
    resp = await api_client.get("/api/v1/watchlist")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == []
    assert "request_id" in body["meta"]


@pytest.mark.asyncio
async def test_add_symbol_to_watchlist(api_client) -> None:
    resp = await api_client.post(
        "/api/v1/watchlist",
        json={"symbol": "aapl", "company_name": "Apple Inc.", "exchange": "NASDAQ"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["symbol"] == "AAPL"
    assert data["is_active"] is True
    assert data["exchange"] == "NASDAQ"


@pytest.mark.asyncio
async def test_add_symbol_duplicate_returns_409(api_client) -> None:
    await api_client.post("/api/v1/watchlist", json={"symbol": "NVDA"})
    resp = await api_client.post("/api/v1/watchlist", json={"symbol": "nvda"})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_list_watchlist_shows_added_symbol(api_client) -> None:
    await api_client.post("/api/v1/watchlist", json={"symbol": "TSLA"})
    resp = await api_client.get("/api/v1/watchlist")
    symbols = [item["symbol"] for item in resp.json()["data"]]
    assert "TSLA" in symbols


@pytest.mark.asyncio
async def test_remove_symbol_from_watchlist(api_client) -> None:
    await api_client.post("/api/v1/watchlist", json={"symbol": "META"})
    resp = await api_client.delete("/api/v1/watchlist/META")
    assert resp.status_code == 200
    assert resp.json()["data"]["removed"] is True

    resp = await api_client.get("/api/v1/watchlist")
    symbols = [item["symbol"] for item in resp.json()["data"]]
    assert "META" not in symbols


@pytest.mark.asyncio
async def test_remove_nonexistent_symbol_returns_404(api_client) -> None:
    resp = await api_client.delete("/api/v1/watchlist/FAKE")
    assert resp.status_code == 404
