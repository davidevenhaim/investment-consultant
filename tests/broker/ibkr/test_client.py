"""Tests for IBKRClient — no real network calls."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from broker.ibkr.client import IBKRClient, IBKRConnectionConfig
from broker.ibkr.fake_client import FakeIBKRClient
from core.errors import IBKRConnectionError, IBKRReadOnlyError

# ── IBKRConnectionConfig / construction ───────────────────────────────────────


def test_client_importable_without_connecting() -> None:
    cfg = IBKRConnectionConfig(
        host="localhost", port=7497, client_id=1, readonly=True, timeout_seconds=5
    )
    client = IBKRClient(cfg)
    assert client.broker_account_id is None


def test_readonly_false_raises_on_construction() -> None:
    cfg = IBKRConnectionConfig(
        host="localhost", port=7497, client_id=1, readonly=False, timeout_seconds=5
    )
    with pytest.raises(IBKRReadOnlyError):
        IBKRClient(cfg)


def test_from_settings_builds_correct_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IBKR_HOST", "tws-host")
    monkeypatch.setenv("IBKR_PORT", "7496")
    monkeypatch.setenv("IBKR_CLIENT_ID", "2")
    monkeypatch.setenv("IBKR_READONLY", "true")
    monkeypatch.setenv("IBKR_TIMEOUT_SECONDS", "15")
    from core.config import get_settings

    get_settings.cache_clear()

    client = IBKRClient.from_settings()
    assert client._cfg.host == "tws-host"
    assert client._cfg.port == 7496
    assert client._cfg.client_id == 2
    assert client._cfg.readonly is True
    assert client._cfg.timeout_seconds == 15
    assert client._cfg.connection_mode == "LOCAL_TWS"

    get_settings.cache_clear()


def test_from_broker_account_local_tws() -> None:
    account = MagicMock()
    account.id = "00000000-0000-0000-0000-000000000001"
    account.connection_mode = "LOCAL_TWS"
    account.host = "my-tws-host"
    account.port = 7497
    account.client_id = 3
    account.readonly = True
    account.display_name = "Test Account"

    client = IBKRClient.from_broker_account(account)
    assert client._cfg.host == "my-tws-host"
    assert client._cfg.port == 7497
    assert client._cfg.client_id == 3
    assert client._cfg.connection_mode == "LOCAL_TWS"
    assert client._cfg.broker_account_id == "00000000-0000-0000-0000-000000000001"


def test_from_broker_account_local_tws_falls_back_to_settings_when_no_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IBKR_HOST", "settings-host")
    monkeypatch.setenv("IBKR_PORT", "7497")
    from core.config import get_settings

    get_settings.cache_clear()

    account = MagicMock()
    account.id = "00000000-0000-0000-0000-000000000002"
    account.connection_mode = "LOCAL_TWS"
    account.host = None
    account.port = None
    account.client_id = 1
    account.readonly = True
    account.display_name = "Fallback Account"

    client = IBKRClient.from_broker_account(account)
    assert client._cfg.host == "settings-host"
    assert client._cfg.port == 7497

    get_settings.cache_clear()


def test_from_broker_account_hosted_gateway_requires_host() -> None:
    account = MagicMock()
    account.id = "00000000-0000-0000-0000-000000000003"
    account.connection_mode = "HOSTED_GATEWAY"
    account.host = None
    account.port = 4002
    account.client_id = 1
    account.readonly = True
    account.display_name = "Hosted Gateway Missing Host"

    with pytest.raises(IBKRConnectionError, match="missing host/port"):
        IBKRClient.from_broker_account(account)


def test_from_broker_account_hosted_gateway_requires_port() -> None:
    account = MagicMock()
    account.id = "00000000-0000-0000-0000-000000000004"
    account.connection_mode = "HOSTED_GATEWAY"
    account.host = "ibkr-gateway-dev"
    account.port = None
    account.client_id = 1
    account.readonly = True
    account.display_name = "Hosted Gateway Missing Port"

    with pytest.raises(IBKRConnectionError, match="missing host/port"):
        IBKRClient.from_broker_account(account)


def test_from_broker_account_hosted_gateway_ok() -> None:
    account = MagicMock()
    account.id = "00000000-0000-0000-0000-000000000005"
    account.connection_mode = "HOSTED_GATEWAY"
    account.host = "ibkr-gateway-dev"
    account.port = 4002
    account.client_id = 1
    account.readonly = True
    account.display_name = "Hosted Gateway OK"

    client = IBKRClient.from_broker_account(account)
    assert client._cfg.host == "ibkr-gateway-dev"
    assert client._cfg.port == 4002
    assert client._cfg.connection_mode == "HOSTED_GATEWAY"


# ── Connection failure → IBKRConnectionError ──────────────────────────────────


@pytest.mark.asyncio
async def test_connection_failure_raises_ibkr_connection_error() -> None:
    cfg = IBKRConnectionConfig(
        host="localhost", port=7497, client_id=1, readonly=True, timeout_seconds=1
    )
    client = IBKRClient(cfg)

    mock_ib = MagicMock()
    mock_ib.connectAsync = AsyncMock(side_effect=OSError("Connection refused"))
    mock_ib_class = MagicMock(return_value=mock_ib)

    with (
        patch("broker.ibkr.client.IBKRClient.connect", wraps=client.connect),
        patch.dict("sys.modules", {"ib_insync": MagicMock(IB=mock_ib_class)}),
        pytest.raises(IBKRConnectionError, match="Connection refused"),
    ):
        await client.connect()


@pytest.mark.asyncio
async def test_timeout_raises_ibkr_connection_error() -> None:
    import asyncio

    cfg = IBKRConnectionConfig(
        host="localhost", port=7497, client_id=1, readonly=True, timeout_seconds=1
    )
    client = IBKRClient(cfg)

    async def slow_connect(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(10)

    mock_ib = MagicMock()
    mock_ib.connectAsync = slow_connect
    mock_ib_class = MagicMock(return_value=mock_ib)

    with (
        patch.dict("sys.modules", {"ib_insync": MagicMock(IB=mock_ib_class)}),
        pytest.raises(IBKRConnectionError, match="timed out"),
    ):
        await client.connect()


@pytest.mark.asyncio
async def test_import_error_raises_ibkr_connection_error() -> None:
    cfg = IBKRConnectionConfig(
        host="localhost", port=7497, client_id=1, readonly=True, timeout_seconds=5
    )
    client = IBKRClient(cfg)

    with (
        patch.dict("sys.modules", {"ib_insync": None}),
        pytest.raises((IBKRConnectionError, ImportError)),
    ):
        await client.connect()


# ── No run_in_executor in client ──────────────────────────────────────────────


def test_no_run_in_executor_in_client_source() -> None:
    import inspect

    import broker.ibkr.client as client_mod

    source = inspect.getsource(client_mod)
    assert "run_in_executor" not in source, (
        "IBKRClient must not use run_in_executor — causes event-loop threading bugs"
    )


def test_no_get_event_loop_in_client_source() -> None:
    import inspect

    import broker.ibkr.client as client_mod

    source = inspect.getsource(client_mod)
    assert "get_event_loop" not in source, (
        "IBKRClient must not call asyncio.get_event_loop() — use get_running_loop() or avoid"
    )


# ── FakeIBKRClient ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fake_client_connect_disconnect() -> None:
    client = FakeIBKRClient()
    assert not client._connected
    await client.connect()
    assert client._connected
    await client.disconnect()
    assert not client._connected


@pytest.mark.asyncio
async def test_fake_client_context_manager() -> None:
    client = FakeIBKRClient()
    async with client.connected() as c:
        assert c._connected
    assert not client._connected


@pytest.mark.asyncio
async def test_fake_client_fetch_executions() -> None:
    from broker.ibkr.fake_client import _FAKE_EXECUTIONS

    client = FakeIBKRClient()
    execs = await client.fetch_executions()
    assert len(execs) == len(_FAKE_EXECUTIONS)
