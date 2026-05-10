"""Tests for trade history service (no live DB — uses mock repositories)."""

from __future__ import annotations

import datetime as dt
from unittest.mock import AsyncMock, MagicMock

import pytest
from broker.ibkr.fake_client import _FAKE_EXECUTIONS, FakeIBKRClient
from broker.ibkr.schemas import IBKRExecution
from portfolio.trade_history_service import (
    sync_ibkr_executions,
)


def _make_exec(exec_id: str, symbol: str, side: str, qty: float, price: float, days_ago: int) -> IBKRExecution:
    ts = dt.datetime(2025, 1, 1, tzinfo=dt.UTC) + dt.timedelta(days=days_ago)
    return IBKRExecution(
        exec_id=exec_id,
        account_id_ibkr="DU999",
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        quantity=qty,
        price=price,
        executed_at=ts,
    )


class TestSyncIBKRExecutions:
    @pytest.mark.asyncio
    async def test_inserts_new_executions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = AsyncMock()

        import portfolio.trade_history_service as svc

        repo_mock = AsyncMock()
        repo_mock.exists_by_exec_id.return_value = False
        repo_mock.create.return_value = MagicMock()

        monkeypatch.setattr(svc, "IBKRExecutionRepository", lambda s: repo_mock)

        execs = [
            _make_exec("e1", "AAPL", "BUY", 10, 100, 0),
            _make_exec("e2", "AAPL", "SELL", 10, 120, 30),
        ]

        inserted = await sync_ibkr_executions(session, execs)
        assert inserted == 2
        assert repo_mock.create.call_count == 2

    @pytest.mark.asyncio
    async def test_skips_duplicates(self, monkeypatch: pytest.MonkeyPatch) -> None:
        session = AsyncMock()

        import portfolio.trade_history_service as svc

        repo_mock = AsyncMock()
        repo_mock.exists_by_exec_id.return_value = True  # all already exist

        monkeypatch.setattr(svc, "IBKRExecutionRepository", lambda s: repo_mock)

        execs = [_make_exec("e1", "AAPL", "BUY", 10, 100, 0)]
        inserted = await sync_ibkr_executions(session, execs)
        assert inserted == 0
        repo_mock.create.assert_not_called()


class TestFakeIBKRClient:
    @pytest.mark.asyncio
    async def test_fetch_executions(self) -> None:
        client = FakeIBKRClient()
        execs = await client.fetch_executions()
        assert len(execs) == len(_FAKE_EXECUTIONS)
        assert all(isinstance(e, IBKRExecution) for e in execs)

    @pytest.mark.asyncio
    async def test_custom_executions(self) -> None:
        custom = [_make_exec("c1", "MSFT", "BUY", 5, 300, 0)]
        client = FakeIBKRClient(executions=custom)
        execs = await client.fetch_executions()
        assert len(execs) == 1
        assert execs[0].symbol == "MSFT"

    @pytest.mark.asyncio
    async def test_context_manager(self) -> None:
        client = FakeIBKRClient()
        assert not client._connected
        async with client.connected() as c:
            assert c._connected
        assert not client._connected
