"""FakeIBKRClient for tests — deterministic AAPL/NVDA/TSLA data, no TWS needed."""

from __future__ import annotations

import datetime as dt
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from broker.ibkr.schemas import IBKRAccountInfo, IBKRExecution

_ACCOUNT = "DU123456"

_FAKE_EXECUTIONS: list[IBKRExecution] = [
    # AAPL: BUY 10 @ 150, SELL 10 @ 180 → winner +20%
    IBKRExecution(
        exec_id="aapl-buy-001",
        account_id_ibkr=_ACCOUNT,
        symbol="AAPL",
        exchange="NASDAQ",
        side="BUY",
        quantity=10.0,
        price=150.0,
        commission=1.0,
        executed_at=dt.datetime(2025, 1, 10, 10, 0, tzinfo=dt.UTC),
    ),
    IBKRExecution(
        exec_id="aapl-sell-001",
        account_id_ibkr=_ACCOUNT,
        symbol="AAPL",
        exchange="NASDAQ",
        side="SELL",
        quantity=10.0,
        price=180.0,
        commission=1.0,
        executed_at=dt.datetime(2025, 3, 15, 14, 30, tzinfo=dt.UTC),
    ),
    # NVDA: BUY 5 @ 400, SELL 5 @ 350 → loser -12.5%
    IBKRExecution(
        exec_id="nvda-buy-001",
        account_id_ibkr=_ACCOUNT,
        symbol="NVDA",
        exchange="NASDAQ",
        side="BUY",
        quantity=5.0,
        price=400.0,
        commission=1.0,
        executed_at=dt.datetime(2025, 2, 1, 9, 30, tzinfo=dt.UTC),
    ),
    IBKRExecution(
        exec_id="nvda-sell-001",
        account_id_ibkr=_ACCOUNT,
        symbol="NVDA",
        exchange="NASDAQ",
        side="SELL",
        quantity=5.0,
        price=350.0,
        commission=1.0,
        executed_at=dt.datetime(2025, 4, 20, 11, 0, tzinfo=dt.UTC),
    ),
    # TSLA: BUY 8 @ 200 — still open (no matching SELL)
    IBKRExecution(
        exec_id="tsla-buy-001",
        account_id_ibkr=_ACCOUNT,
        symbol="TSLA",
        exchange="NASDAQ",
        side="BUY",
        quantity=8.0,
        price=200.0,
        commission=1.0,
        executed_at=dt.datetime(2025, 3, 5, 10, 0, tzinfo=dt.UTC),
    ),
]

_FAKE_ACCOUNT = IBKRAccountInfo(
    account_id=_ACCOUNT,
    net_liquidation=100_000.0,
    cash_balance=25_000.0,
    currency="USD",
)


class FakeIBKRClient:
    """Drop-in replacement for IBKRClient in tests. No network calls."""

    def __init__(self, executions: list[IBKRExecution] | None = None) -> None:
        self._executions = executions if executions is not None else list(_FAKE_EXECUTIONS)
        self._connected = False

    async def connect(self) -> None:
        self._connected = True

    async def disconnect(self) -> None:
        self._connected = False

    @asynccontextmanager
    async def connected(self) -> AsyncIterator[FakeIBKRClient]:
        await self.connect()
        try:
            yield self
        finally:
            await self.disconnect()

    async def account_id(self) -> str:
        return _ACCOUNT

    async def fetch_executions(self, months: int = 12) -> list[IBKRExecution]:
        """Return fake executions directly — bypasses trade_history.fetch_executions."""
        return list(self._executions)

    @property
    def fake_account(self) -> IBKRAccountInfo:
        return _FAKE_ACCOUNT
