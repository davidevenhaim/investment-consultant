"""Fetch IBKR execution history via ib_insync."""

from __future__ import annotations

import asyncio
import datetime as dt
import logging
from typing import TYPE_CHECKING

from broker.ibkr.mapper import map_execution

if TYPE_CHECKING:
    from broker.ibkr.client import IBKRClient
    from broker.ibkr.schemas import IBKRExecution

logger = logging.getLogger(__name__)


async def fetch_executions(client: IBKRClient, months: int = 12) -> list[IBKRExecution]:
    """Pull execution history for the last `months` months.

    Returns deduplicated list ordered by executed_at ascending.
    """
    loop = asyncio.get_event_loop()

    account_id = await client.account_id()

    # Build ib_insync ExecutionFilter for date range
    import ib_insync  # noqa: PLC0415

    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=months * 31)
    exec_filter = ib_insync.ExecutionFilter(
        clientId=0,
        time=since.strftime("%Y%m%d-%H:%M:%S"),
    )

    trades = await loop.run_in_executor(
        None,
        lambda: client.ib.reqExecutions(exec_filter),  # type: ignore[attr-defined]
    )

    seen: set[str] = set()
    executions: list[IBKRExecution] = []
    for fill in trades:
        exec_obj = fill.execution if hasattr(fill, "execution") else fill
        exec_id = str(exec_obj.execId)
        if exec_id in seen:
            continue
        seen.add(exec_id)
        try:
            ex = map_execution(exec_obj, account_id)
            executions.append(ex)
        except Exception as exc:
            logger.warning("ibkr_exec_map_failed", extra={"exec_id": exec_id, "error": str(exc)})

    executions.sort(key=lambda e: e.executed_at)
    logger.info("ibkr_executions_fetched", extra={"count": len(executions), "months": months})
    return executions
