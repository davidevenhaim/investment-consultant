"""Research run API tests — require DB."""
import pytest


@pytest.mark.asyncio
async def test_create_run_with_empty_watchlist_fails(api_client) -> None:
    resp = await api_client.post("/api/v1/research-runs", json={})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_run_with_explicit_symbols(api_client) -> None:
    resp = await api_client.post(
        "/api/v1/research-runs",
        json={"run_type": "MANUAL", "symbols": ["AAPL", "NVDA"]},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["run_type"] == "MANUAL"
    assert data["status"] == "CREATED"
    assert len(data["tickers"]) == 2
    ticker_symbols = {t["symbol"] for t in data["tickers"]}
    assert ticker_symbols == {"AAPL", "NVDA"}


@pytest.mark.asyncio
async def test_create_run_tickers_have_created_status(api_client) -> None:
    resp = await api_client.post(
        "/api/v1/research-runs",
        json={"symbols": ["TSLA"]},
    )
    assert resp.status_code == 201
    tickers = resp.json()["data"]["tickers"]
    assert all(t["status"] == "CREATED" for t in tickers)


@pytest.mark.asyncio
async def test_create_run_uses_watchlist_when_no_symbols(api_client) -> None:
    # Add to watchlist first
    await api_client.post("/api/v1/watchlist", json={"symbol": "AAPL"})
    await api_client.post("/api/v1/watchlist", json={"symbol": "NVDA"})

    resp = await api_client.post("/api/v1/research-runs", json={})
    assert resp.status_code == 201
    symbols = {t["symbol"] for t in resp.json()["data"]["tickers"]}
    assert {"AAPL", "NVDA"}.issubset(symbols)


@pytest.mark.asyncio
async def test_get_run_by_id(api_client) -> None:
    create = await api_client.post(
        "/api/v1/research-runs", json={"symbols": ["AAPL"]}
    )
    run_id = create.json()["data"]["id"]

    resp = await api_client.get(f"/api/v1/research-runs/{run_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == run_id


@pytest.mark.asyncio
async def test_get_nonexistent_run_returns_404(api_client) -> None:
    import uuid
    resp = await api_client.get(f"/api/v1/research-runs/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_research_runs(api_client) -> None:
    await api_client.post("/api/v1/research-runs", json={"symbols": ["AAPL"]})
    await api_client.post("/api/v1/research-runs", json={"symbols": ["NVDA"]})

    resp = await api_client.get("/api/v1/research-runs")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) >= 2
