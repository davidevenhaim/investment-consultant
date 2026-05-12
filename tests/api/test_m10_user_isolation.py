"""M10.1 user-scoped API behavior."""

import datetime as dt
import uuid

import pytest

USER_A = uuid.UUID("10000000-0000-0000-0000-000000000001")
USER_B = uuid.UUID("20000000-0000-0000-0000-000000000002")
HEADERS_A = {"X-User-Id": str(USER_A)}
HEADERS_B = {"X-User-Id": str(USER_B)}


@pytest.mark.asyncio
async def test_watchlist_is_scoped_by_user(api_client) -> None:
    await api_client.post("/api/v1/watchlist", json={"symbol": "AAPL"}, headers=HEADERS_A)

    resp_b = await api_client.get("/api/v1/watchlist", headers=HEADERS_B)
    assert resp_b.status_code == 200
    assert resp_b.json()["data"] == []

    create_b = await api_client.post(
        "/api/v1/watchlist",
        json={"symbol": "AAPL"},
        headers=HEADERS_B,
    )
    assert create_b.status_code == 201


@pytest.mark.asyncio
async def test_research_run_id_routes_are_scoped_by_user(api_client) -> None:
    created = await api_client.post(
        "/api/v1/research-runs",
        json={"symbols": ["AAPL"]},
        headers=HEADERS_A,
    )
    assert created.status_code == 201
    run_id = created.json()["data"]["id"]

    visible = await api_client.get(f"/api/v1/research-runs/{run_id}", headers=HEADERS_A)
    assert visible.status_code == 200

    hidden = await api_client.get(f"/api/v1/research-runs/{run_id}", headers=HEADERS_B)
    assert hidden.status_code == 404

    hidden_recs = await api_client.get(
        f"/api/v1/research-runs/{run_id}/recommendations",
        headers=HEADERS_B,
    )
    assert hidden_recs.status_code == 404


@pytest.mark.asyncio
async def test_latest_recommendations_are_scoped_by_user(api_client) -> None:
    await api_client.post(
        "/api/v1/research-runs",
        json={"symbols": ["TSLA"]},
        headers=HEADERS_A,
    )
    await api_client.post(
        "/api/v1/research-runs",
        json={"symbols": ["NVDA"]},
        headers=HEADERS_B,
    )

    latest_a = await api_client.get("/api/v1/recommendations/latest", headers=HEADERS_A)
    assert latest_a.status_code == 200
    assert {item["symbol"] for item in latest_a.json()["data"]} == {"TSLA"}

    latest_b = await api_client.get("/api/v1/recommendations/latest", headers=HEADERS_B)
    assert latest_b.status_code == 200
    assert {item["symbol"] for item in latest_b.json()["data"]} == {"NVDA"}


@pytest.mark.asyncio
async def test_broker_accounts_are_scoped_by_user(api_client) -> None:
    created = await api_client.post(
        "/api/v1/portfolio/broker-accounts",
        json={"display_name": "User A TWS"},
        headers=HEADERS_A,
    )
    assert created.status_code == 200
    account_id = created.json()["data"]["id"]

    list_b = await api_client.get("/api/v1/portfolio/broker-accounts", headers=HEADERS_B)
    assert list_b.status_code == 200
    assert list_b.json()["data"] == []

    get_b = await api_client.get(
        f"/api/v1/portfolio/broker-accounts/{account_id}",
        headers=HEADERS_B,
    )
    assert get_b.status_code == 404


@pytest.mark.asyncio
async def test_manual_trades_are_scoped_by_user(api_client) -> None:
    trade = {
        "symbol": "AAPL",
        "side": "BUY",
        "quantity": 1,
        "price": 100,
        "executed_at": dt.datetime(2026, 1, 1, tzinfo=dt.UTC).isoformat(),
    }
    created = await api_client.post(
        "/api/v1/portfolio/trades",
        json=trade,
        headers=HEADERS_A,
    )
    assert created.status_code == 200

    trades_a = await api_client.get("/api/v1/portfolio/trades", headers=HEADERS_A)
    assert trades_a.status_code == 200
    assert trades_a.json()["data"]["count"] == 1

    trades_b = await api_client.get("/api/v1/portfolio/trades", headers=HEADERS_B)
    assert trades_b.status_code == 200
    assert trades_b.json()["data"] == {"trades": [], "count": 0}
