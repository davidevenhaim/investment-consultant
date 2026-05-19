"""Tests for the isolated IBKR sync runner — no real network, no real event loop conflicts."""

from __future__ import annotations

import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from broker.ibkr.client import IBKRConnectionConfig
from broker.ibkr.schemas import IBKRExecution
from broker.ibkr.sync_runner import fetch_executions_isolated
from core.errors import IBKRConnectionError


def _make_config() -> IBKRConnectionConfig:
    return IBKRConnectionConfig(
        host="localhost",
        port=7497,
        client_id=1,
        readonly=True,
        timeout_seconds=5,
        connection_mode="LOCAL_TWS",
    )


def _make_exec(exec_id: str = "e1") -> IBKRExecution:
    import datetime as dt

    return IBKRExecution(
        exec_id=exec_id,
        account_id_ibkr="DU999",
        symbol="AAPL",
        side="BUY",
        quantity=10.0,
        price=150.0,
        executed_at=dt.datetime(2025, 1, 1, tzinfo=dt.UTC),
    )


# ── fetch_executions_isolated is synchronous ──────────────────────────────────


def test_fetch_executions_isolated_is_synchronous() -> None:
    """Must be a regular function, not a coroutine — asyncio.to_thread needs sync."""
    assert not asyncio.iscoroutinefunction(fetch_executions_isolated)
    assert not inspect.iscoroutinefunction(fetch_executions_isolated)


# ── isolated fetch runs in a fresh event loop ─────────────────────────────────


def test_fetch_executions_isolated_creates_own_event_loop() -> None:
    """asyncio.run() inside the isolated function always creates a fresh loop.

    We verify this by patching asyncio.run and confirming it's called.
    """
    fake_execs = [_make_exec()]
    config = _make_config()

    with patch("broker.ibkr.sync_runner.asyncio.run", return_value=fake_execs) as mock_run:
        result = fetch_executions_isolated(config, months=1)

    mock_run.assert_called_once()
    assert result == fake_execs


@pytest.mark.asyncio
async def test_isolated_fetch_callable_from_to_thread() -> None:
    """asyncio.to_thread(fetch_executions_isolated, ...) works without loop conflict."""
    fake_execs = [_make_exec("thread-test")]
    config = _make_config()

    with patch("broker.ibkr.sync_runner.asyncio.run", return_value=fake_execs):
        result = await asyncio.to_thread(fetch_executions_isolated, config, 12)

    assert result == fake_execs


# ── IBKRConnectionError propagates cleanly ───────────────────────────────────


def test_ibkr_connection_error_propagates_from_isolated_fetch() -> None:
    """IBKRConnectionError raised inside asyncio.run propagates to the caller."""
    config = _make_config()

    with (
        patch(
            "broker.ibkr.sync_runner.asyncio.run",
            side_effect=IBKRConnectionError("Connection refused (localhost:7497)"),
        ),
        pytest.raises(IBKRConnectionError, match="Connection refused"),
    ):
        fetch_executions_isolated(config, months=12)


@pytest.mark.asyncio
async def test_ibkr_connection_error_propagates_through_to_thread() -> None:
    """IBKRConnectionError propagates through asyncio.to_thread to the awaiting caller."""
    config = _make_config()

    with (
        patch(
            "broker.ibkr.sync_runner.asyncio.run",
            side_effect=IBKRConnectionError("Connection timed out"),
        ),
        pytest.raises(IBKRConnectionError, match="timed out"),
    ):
        await asyncio.to_thread(fetch_executions_isolated, config, 12)


# ── Real async path via mocked ib_insync ─────────────────────────────────────


def test_fetch_executions_isolated_with_mocked_ibkr() -> None:
    """End-to-end: mocked ib_insync returns fake executions through the full path."""
    from broker.ibkr.fake_client import _FAKE_EXECUTIONS

    config = _make_config()

    # Patch IBKRClient inside the isolated coroutine
    mock_client_instance = MagicMock()
    mock_client_instance.connected = MagicMock()
    mock_client_instance.connected.return_value.__aenter__ = AsyncMock(
        return_value=mock_client_instance
    )
    mock_client_instance.connected.return_value.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "broker.ibkr.sync_runner.asyncio.run",
        return_value=list(_FAKE_EXECUTIONS),
    ):
        result = fetch_executions_isolated(config, months=12)

    assert len(result) == len(_FAKE_EXECUTIONS)


# ── No direct event-loop usage in sync_runner ─────────────────────────────────


def test_sync_runner_does_not_call_get_event_loop() -> None:
    import broker.ibkr.sync_runner as runner_mod

    source = inspect.getsource(runner_mod)
    assert "get_event_loop" not in source, (
        "sync_runner must not call asyncio.get_event_loop() — "
        "it uses asyncio.run() which creates its own loop"
    )


def test_sync_runner_does_not_use_run_in_executor() -> None:
    import broker.ibkr.sync_runner as runner_mod

    source = inspect.getsource(runner_mod)
    assert "run_in_executor" not in source, (
        "sync_runner must not use run_in_executor — that passes work back to the calling loop"
    )
