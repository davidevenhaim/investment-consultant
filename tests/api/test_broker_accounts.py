"""Tests for broker account API endpoints."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_broker_accounts_empty(api_client: AsyncClient) -> None:
    resp = await api_client.get("/api/v1/portfolio/broker-accounts")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert isinstance(data, list)


@pytest.mark.asyncio
async def test_create_broker_account_local_tws(api_client: AsyncClient) -> None:
    body = {
        "provider": "IBKR",
        "display_name": "My Paper TWS",
        "connection_mode": "LOCAL_TWS",
        "host": "host.docker.internal",
        "port": 7497,
        "client_id": 1,
        "readonly": True,
        "is_active": True,
    }
    resp = await api_client.post("/api/v1/portfolio/broker-accounts", json=body)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["provider"] == "IBKR"
    assert data["display_name"] == "My Paper TWS"
    assert data["connection_mode"] == "LOCAL_TWS"
    assert data["readonly"] is True
    assert "id" in data


@pytest.mark.asyncio
async def test_create_broker_account_hosted_gateway(api_client: AsyncClient) -> None:
    body = {
        "provider": "IBKR",
        "display_name": "Hosted IB Gateway - Dev",
        "connection_mode": "HOSTED_GATEWAY",
        "host": "ibkr-gateway-dev",
        "port": 4002,
        "client_id": 1,
        "readonly": True,
        "metadata_json": {
            "gateway_container_name": "ibkr-gateway-dev",
            "secret_ref": "local-dev-only",
        },
    }
    resp = await api_client.post("/api/v1/portfolio/broker-accounts", json=body)
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["connection_mode"] == "HOSTED_GATEWAY"
    assert data["metadata_json"]["gateway_container_name"] == "ibkr-gateway-dev"


@pytest.mark.asyncio
async def test_create_broker_account_readonly_false_rejected(api_client: AsyncClient) -> None:
    body = {
        "provider": "IBKR",
        "display_name": "Bad Account",
        "connection_mode": "LOCAL_TWS",
        "readonly": False,  # must be True
    }
    resp = await api_client.post("/api/v1/portfolio/broker-accounts", json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_broker_account_bad_provider_rejected(api_client: AsyncClient) -> None:
    body = {
        "provider": "SCHWAB",  # only IBKR supported now
        "display_name": "Schwab Account",
        "connection_mode": "LOCAL_TWS",
        "readonly": True,
    }
    resp = await api_client.post("/api/v1/portfolio/broker-accounts", json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_broker_account_password_in_metadata_rejected(
    api_client: AsyncClient,
) -> None:
    body = {
        "provider": "IBKR",
        "display_name": "Bad Metadata",
        "connection_mode": "LOCAL_TWS",
        "readonly": True,
        "metadata_json": {"password": "oops"},
    }
    resp = await api_client.post("/api/v1/portfolio/broker-accounts", json=body)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_broker_account_token_in_metadata_rejected(
    api_client: AsyncClient,
) -> None:
    for bad_key in ("password", "username", "secret", "token", "api_key"):
        body = {
            "provider": "IBKR",
            "display_name": f"Bad Metadata {bad_key}",
            "connection_mode": "LOCAL_TWS",
            "readonly": True,
            "metadata_json": {bad_key: "oops"},
        }
        resp = await api_client.post("/api/v1/portfolio/broker-accounts", json=body)
        assert resp.status_code == 422, f"Expected 422 for key '{bad_key}'"


@pytest.mark.asyncio
async def test_get_broker_account_by_id(api_client: AsyncClient) -> None:
    # Create first
    body = {
        "provider": "IBKR",
        "display_name": "Get By ID Test",
        "connection_mode": "LOCAL_TWS",
        "readonly": True,
    }
    create_resp = await api_client.post("/api/v1/portfolio/broker-accounts", json=body)
    account_id = create_resp.json()["data"]["id"]

    resp = await api_client.get(f"/api/v1/portfolio/broker-accounts/{account_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["id"] == account_id


@pytest.mark.asyncio
async def test_get_broker_account_not_found(api_client: AsyncClient) -> None:
    resp = await api_client.get(
        "/api/v1/portfolio/broker-accounts/00000000-0000-0000-0000-000000000099"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_patch_broker_account(api_client: AsyncClient) -> None:
    body = {
        "provider": "IBKR",
        "display_name": "Patch Test",
        "connection_mode": "LOCAL_TWS",
        "readonly": True,
    }
    create_resp = await api_client.post("/api/v1/portfolio/broker-accounts", json=body)
    account_id = create_resp.json()["data"]["id"]

    patch_resp = await api_client.patch(
        f"/api/v1/portfolio/broker-accounts/{account_id}",
        json={"display_name": "Updated Name"},
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["data"]["display_name"] == "Updated Name"


@pytest.mark.asyncio
async def test_sync_ibkr_disabled_returns_503(api_client: AsyncClient) -> None:
    """sync-ibkr returns 503 when IBKR_ENABLED=false (conftest default)."""
    resp = await api_client.post("/api/v1/portfolio/sync-ibkr")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_sync_ibkr_for_account_disabled_returns_503(api_client: AsyncClient) -> None:
    # Create account first
    body = {
        "provider": "IBKR",
        "display_name": "Sync Test",
        "connection_mode": "LOCAL_TWS",
        "readonly": True,
    }
    create_resp = await api_client.post("/api/v1/portfolio/broker-accounts", json=body)
    account_id = create_resp.json()["data"]["id"]

    resp = await api_client.post(
        f"/api/v1/portfolio/broker-accounts/{account_id}/sync-ibkr"
    )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_list_shows_created_account(api_client: AsyncClient) -> None:
    body = {
        "provider": "IBKR",
        "display_name": "List Test Account",
        "connection_mode": "LOCAL_TWS",
        "readonly": True,
    }
    await api_client.post("/api/v1/portfolio/broker-accounts", json=body)

    resp = await api_client.get("/api/v1/portfolio/broker-accounts")
    assert resp.status_code == 200
    names = [a["display_name"] for a in resp.json()["data"]]
    assert "List Test Account" in names


@pytest.mark.asyncio
async def test_sync_flex_creates_visible_dev_default_account(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IBKR_FLEX_ENABLED", "true")
    monkeypatch.setenv("IBKR_FLEX_TOKEN", "test-token")
    monkeypatch.setenv("IBKR_FLEX_QUERY_ID", "test-query")
    from core.config import get_settings

    get_settings.cache_clear()

    async def fake_sync(db, broker_account_id, token, query_id):
        return {
            "fetched": 0,
            "inserted": 0,
            "profile_snapshot_id": "00000000-0000-0000-0000-000000000001",
        }

    monkeypatch.setattr(
        "portfolio.trade_history_service.sync_ibkr_flex_executions",
        fake_sync,
    )

    sync_resp = await api_client.post("/api/v1/portfolio/sync-flex")
    assert sync_resp.status_code == 200

    list_resp = await api_client.get("/api/v1/portfolio/broker-accounts")
    assert list_resp.status_code == 200
    accounts = list_resp.json()["data"]
    assert len(accounts) == 1
    assert accounts[0]["display_name"] == "Dev Default (LOCAL_TWS)"

    get_settings.cache_clear()


# ── Isolated sync path (IBKR_ENABLED=true) ───────────────────────────────────


@pytest.mark.asyncio
async def test_sync_ibkr_enabled_uses_isolated_runner_returns_inserted(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With IBKR_ENABLED=true, router calls isolated runner; mocked to return 0 execs."""
    import datetime as dt

    from broker.ibkr.schemas import IBKRExecution

    monkeypatch.setenv("IBKR_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    fake_exec = IBKRExecution(
        exec_id="test-isolated-001",
        account_id_ibkr="DU999",
        symbol="AAPL",
        side="BUY",
        quantity=10.0,
        price=150.0,
        executed_at=dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
    )

    async def fake_to_thread(fn: object, *args: object, **kwargs: object) -> list[IBKRExecution]:
        return [fake_exec]

    import asyncio  # noqa: PLC0415
    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    resp = await api_client.post("/api/v1/portfolio/sync-ibkr")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert "inserted" in data
    assert "message" in data

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_sync_ibkr_connection_error_returns_503(
    api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """IBKRConnectionError from isolated runner surfaces as 503, not 500."""
    from core.errors import IBKRConnectionError

    monkeypatch.setenv("IBKR_ENABLED", "true")
    from core.config import get_settings
    get_settings.cache_clear()

    import asyncio  # noqa: PLC0415

    async def fail_to_thread(fn: object, *args: object, **kwargs: object) -> None:
        raise IBKRConnectionError("Connection refused (localhost:7497)")

    monkeypatch.setattr(asyncio, "to_thread", fail_to_thread)

    resp = await api_client.post("/api/v1/portfolio/sync-ibkr")
    assert resp.status_code == 503
    assert "Connection refused" in resp.json()["detail"]

    get_settings.cache_clear()
