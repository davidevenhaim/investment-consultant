"""Fetch IBKR execution history via ib_insync.

IMPORTANT — IBKR reqExecutions / reqExecutionsAsync limitations:
  - reqExecutions returns ONLY executions from the current TWS/Gateway session.
  - The ExecutionFilter.time field filters within the current session only,
    not across calendar months of history.
  - For true 12-month trade history, IBKR Flex Query Reports are required
    (implemented in a future milestone via the IBKR Flex Web Service API).
  - Until then, this fetch captures whatever the current session has seen,
    which is typically the current trading day or since last TWS restart.

References:
  https://interactivebrokers.github.io/tws-api/classIBApi_1_1EClient.html#a32b422f40b24a2e6a86843e1e45617d5
  https://www.interactivebrokers.com/en/trading/flex-queries.php
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from broker.ibkr.client import IBKRClient
    from broker.ibkr.schemas import IBKRExecution

logger = logging.getLogger(__name__)


async def fetch_executions(client: IBKRClient, months: int = 12) -> list[IBKRExecution]:
    """Pull executions visible in the current TWS/Gateway session.

    NOTE: reqExecutions only returns executions from the *current session*.
    The `months` parameter documents intent but IBKR does not guarantee
    historical data beyond the current session. See module docstring.

    Returns deduplicated list ordered by executed_at ascending.
    """
    from ib_insync import ExecutionFilter  # noqa: PLC0415

    from broker.ibkr.mapper import map_execution  # noqa: PLC0415

    ib: Any = client.ib  # ib_insync.IB — typed as object in IBKRClient.ib property

    # Gather session diagnostics first (safe — no credentials logged)
    managed_accounts: list[str] = []
    server_time: str | None = None
    try:
        managed_accounts = list(ib.managedAccounts())
    except Exception as exc:  # noqa: BLE001
        logger.warning("ibkr_managed_accounts_failed", extra={"error": str(exc)})

    try:
        server_time = str(ib.reqCurrentTime())
    except Exception as exc:  # noqa: BLE001
        logger.debug("ibkr_server_time_failed", extra={"error": str(exc)})

    account_id = managed_accounts[0] if managed_accounts else ""
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=months * 31)
    # ExecutionFilter.time format required by TWS API: "YYYYMMDD-HH:MM:SS"
    since_str = since.strftime("%Y%m%d-%H:%M:%S")

    # Build filter — acctCode scopes to the first managed account when available
    filter_kwargs: dict[str, Any] = {
        "clientId": 0,  # 0 = all clients
        "time": since_str,
    }
    if account_id:
        filter_kwargs["acctCode"] = account_id

    exec_filter = ExecutionFilter(**filter_kwargs)

    logger.info(
        "ibkr_fetch_executions_request",
        extra={
            "managed_accounts": managed_accounts,
            "server_time": server_time,
            "requested_months": months,
            "since_utc": since_str,
            "filter_client_id": filter_kwargs["clientId"],
            "filter_acct_code": filter_kwargs.get("acctCode", "(none)"),
            "broker_account_id": client.broker_account_id,
            "note": (
                "reqExecutions only returns current-session executions. "
                "For 12-month history, Flex Query is required."
            ),
        },
    )

    fills: list[Any] = await ib.reqExecutionsAsync(exec_filter)
    raw_count = len(fills)

    # Log first/last raw fill timestamps if present (no credential data)
    raw_times: list[str] = []
    for fill in fills:
        import contextlib  # noqa: PLC0415

        with contextlib.suppress(Exception):
            exec_obj = fill.execution if hasattr(fill, "execution") else fill
            raw_times.append(str(exec_obj.time))
    raw_times.sort()

    logger.info(
        "ibkr_raw_fills_received",
        extra={
            "raw_fill_count": raw_count,
            "first_fill_time": raw_times[0] if raw_times else None,
            "last_fill_time": raw_times[-1] if raw_times else None,
            "broker_account_id": client.broker_account_id,
        },
    )

    seen: set[str] = set()
    executions: list[IBKRExecution] = []
    map_errors = 0

    for fill in fills:
        exec_obj = fill.execution if hasattr(fill, "execution") else fill
        exec_id = str(exec_obj.execId)
        if exec_id in seen:
            continue
        seen.add(exec_id)
        try:
            ex = map_execution(exec_obj, account_id)
            executions.append(ex)
        except Exception as exc:
            map_errors += 1
            logger.warning(
                "ibkr_exec_map_failed",
                extra={
                    "exec_id": exec_id,
                    "error": str(exc),
                    "broker_account_id": client.broker_account_id,
                },
            )

    executions.sort(key=lambda e: e.executed_at)

    mapped_times = [str(e.executed_at) for e in executions]

    logger.info(
        "ibkr_executions_fetched",
        extra={
            "raw_count": raw_count,
            "mapped_count": len(executions),
            "map_errors": map_errors,
            "first_execution_at": mapped_times[0] if mapped_times else None,
            "last_execution_at": mapped_times[-1] if mapped_times else None,
            "months": months,
            "broker_account_id": client.broker_account_id,
        },
    )
    return executions


async def fetch_session_diagnostics(client: IBKRClient) -> dict[str, Any]:
    """Return diagnostic info about the connected session — no trade data fetched."""
    ib: Any = client.ib  # ib_insync.IB — typed as object in IBKRClient.ib property

    managed_accounts: list[str] = []
    server_time: str | None = None
    raw_execution_count = 0
    mapped_execution_count = 0
    first_execution_at: str | None = None
    last_execution_at: str | None = None

    try:
        managed_accounts = list(ib.managedAccounts())
    except Exception as exc:  # noqa: BLE001
        logger.warning("ibkr_managed_accounts_failed", extra={"error": str(exc)})

    try:
        server_time = str(ib.reqCurrentTime())
    except Exception as exc:  # noqa: BLE001
        logger.debug("ibkr_server_time_failed", extra={"error": str(exc)})

    try:
        from ib_insync import ExecutionFilter  # noqa: PLC0415

        from broker.ibkr.mapper import map_execution  # noqa: PLC0415

        account_id = managed_accounts[0] if managed_accounts else ""
        exec_filter = ExecutionFilter(
            clientId=0,
            **({"acctCode": account_id} if account_id else {}),
        )
        fills = await ib.reqExecutionsAsync(exec_filter)
        raw_execution_count = len(fills)

        for fill in fills:
            exec_obj = fill.execution if hasattr(fill, "execution") else fill
            import contextlib as _cl  # noqa: PLC0415

            with _cl.suppress(Exception):
                ex = map_execution(exec_obj, account_id)
                mapped_execution_count += 1
                ts = str(ex.executed_at)
                if first_execution_at is None or ts < first_execution_at:
                    first_execution_at = ts
                if last_execution_at is None or ts > last_execution_at:
                    last_execution_at = ts
    except Exception as exc:  # noqa: BLE001
        logger.warning("ibkr_diagnostics_exec_fetch_failed", extra={"error": str(exc)})

    return {
        "managed_accounts": managed_accounts,
        "server_time": server_time,
        "raw_execution_count": raw_execution_count,
        "mapped_execution_count": mapped_execution_count,
        "first_execution_at": first_execution_at,
        "last_execution_at": last_execution_at,
        "note": (
            "reqExecutions only returns current-session executions. "
            "0 results with an active account likely means no trades this session. "
            "For 12-month history use IBKR Flex Query Reports (future milestone)."
        ),
    }
