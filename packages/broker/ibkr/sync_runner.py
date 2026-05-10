"""Isolated IBKR execution fetch — runs in a dedicated thread with its own event loop.

ib_insync creates internal futures and manages its own event loop. Running it inside
the FastAPI/Uvicorn event loop causes "Future attached to a different loop" errors.

The fix: wrap the entire connect → fetch → disconnect sequence in asyncio.run(),
which creates a *fresh* event loop in the calling thread. Call this function from
async code via asyncio.to_thread so the calling event loop is never blocked or
entangled with ib_insync's internals.

Usage in an async FastAPI handler:
    executions = await asyncio.to_thread(
        fetch_executions_isolated, config, months
    )
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from broker.ibkr.client import IBKRConnectionConfig
    from broker.ibkr.schemas import IBKRExecution

logger = logging.getLogger(__name__)


def fetch_executions_isolated(
    config: IBKRConnectionConfig,
    months: int = 12,
) -> list[IBKRExecution]:
    """Synchronous entry point: runs ib_insync in its own event loop.

    Call via asyncio.to_thread — never call directly from within a running
    event loop, as it will block that loop for the duration of the sync.

    asyncio.run() guarantees a fresh event loop isolated from the caller's loop.
    ib_insync futures are created and resolved entirely within that fresh loop.
    """

    async def _connect_and_fetch() -> list[IBKRExecution]:
        from broker.ibkr.client import IBKRClient
        from broker.ibkr.trade_history import fetch_executions

        client = IBKRClient(config)
        async with client.connected() as c:
            return await fetch_executions(c, months=months)

    logger.info(
        "ibkr_isolated_fetch_start",
        extra={
            "host": config.host,
            "port": config.port,
            "client_id": config.client_id,
            "connection_mode": config.connection_mode,
            "months": months,
            "broker_account_id": config.broker_account_id,
            "display_name": config.display_name,
        },
    )
    result = asyncio.run(_connect_and_fetch())
    logger.info(
        "ibkr_isolated_fetch_done",
        extra={
            "mapped_count": len(result),
            "broker_account_id": config.broker_account_id,
        },
    )
    return result


def run_diagnostics_isolated(config: IBKRConnectionConfig) -> dict[str, Any]:
    """Connect to IBKR and return diagnostic info — no order placement, read-only."""

    async def _connect_and_diagnose() -> dict[str, Any]:
        from broker.ibkr.client import IBKRClient
        from broker.ibkr.trade_history import fetch_session_diagnostics

        client = IBKRClient(config)
        async with client.connected() as c:
            return await fetch_session_diagnostics(c)

    logger.info(
        "ibkr_diagnostics_start",
        extra={
            "host": config.host,
            "port": config.port,
            "client_id": config.client_id,
            "connection_mode": config.connection_mode,
            "broker_account_id": config.broker_account_id,
        },
    )
    return asyncio.run(_connect_and_diagnose())
