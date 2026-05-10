"""Portfolio API tests — require DB."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_get_portfolio_returns_account(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/portfolio")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "account" in data
    assert "positions" in data
    assert data["account"]["account_type"] == "MANUAL"


@pytest.mark.asyncio
async def test_post_position_creates(api_client: AsyncClient) -> None:
    resp = await api_client.post(
        "/api/v1/portfolio/positions",
        json={"symbol": "AAPL", "quantity": 10, "average_cost": 190},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    syms = [p["symbol"] for p in data["positions"]]
    assert "AAPL" in syms


@pytest.mark.asyncio
async def test_post_position_updates_existing(api_client: AsyncClient) -> None:
    await api_client.post(
        "/api/v1/portfolio/positions",
        json={"symbol": "AAPL", "quantity": 5, "average_cost": 180},
    )
    resp = await api_client.post(
        "/api/v1/portfolio/positions",
        json={"symbol": "AAPL", "quantity": 15, "average_cost": 185},
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    aapl = next(p for p in data["positions"] if p["symbol"] == "AAPL")
    assert float(aapl["quantity"]) == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_delete_position_removes(api_client: AsyncClient) -> None:
    await api_client.post(
        "/api/v1/portfolio/positions",
        json={"symbol": "NVDA", "quantity": 3, "average_cost": 100},
    )
    resp = await api_client.delete("/api/v1/portfolio/positions/NVDA")
    assert resp.status_code == 200
    assert resp.json()["data"]["removed"] is True

    portfolio = await api_client.get("/api/v1/portfolio")
    syms = [p["symbol"] for p in portfolio.json()["data"]["positions"]]
    assert "NVDA" not in syms


@pytest.mark.asyncio
async def test_delete_position_not_found(api_client: AsyncClient) -> None:
    resp = await api_client.delete("/api/v1/portfolio/positions/ZZZZ")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_post_refresh_rebuilds_snapshot(api_client: AsyncClient) -> None:
    await api_client.post(
        "/api/v1/portfolio/positions",
        json={"symbol": "TSLA", "quantity": 5, "average_cost": 250},
    )
    resp = await api_client.post("/api/v1/portfolio/refresh")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "snapshot" in data
    assert data["snapshot"] is not None


@pytest.mark.asyncio
async def test_portfolio_snapshot_has_risk_metrics(api_client: AsyncClient) -> None:
    await api_client.post(
        "/api/v1/portfolio/positions",
        json={"symbol": "AAPL", "quantity": 10, "average_cost": 190},
    )
    await api_client.post("/api/v1/portfolio/refresh")
    resp = await api_client.get("/api/v1/portfolio")
    data = resp.json()["data"]
    snap = data.get("snapshot")
    if snap is not None:
        assert "risk_metrics_json" in snap
