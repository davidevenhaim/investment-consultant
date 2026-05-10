"""IBKR connection + execution diagnostics CLI.

Connects using the same isolated-thread approach as the sync endpoint.
Read-only — no order placement, no write operations to IBKR.

Usage:
    docker compose exec api python -m apps.cli.ibkr_diagnostics

    # With custom host/port:
    docker compose exec api python -m apps.cli.ibkr_diagnostics \
        --host host.docker.internal --port 7497

    # Use specific broker account from DB:
    docker compose exec api python -m apps.cli.ibkr_diagnostics --broker-account-id <uuid>

Output (JSON):
    {
      "connected": true,
      "host": "host.docker.internal",
      "port": 7497,
      "client_id": 1,
      "connection_mode": "LOCAL_TWS",
      "broker_account_id": null,
      "managed_accounts": ["DU1234567"],
      "server_time": "2026-05-10 14:23:01",
      "raw_execution_count": 0,
      "mapped_execution_count": 0,
      "first_execution_at": null,
      "last_execution_at": null,
      "reqExecutions_note": "...",
      "error": null
    }
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any


def _build_config(
    host: str | None = None,
    port: int | None = None,
    client_id: int | None = None,
) -> Any:
    from broker.ibkr.client import IBKRClient

    if host or port or client_id:
        from broker.ibkr.client import IBKRConnectionConfig
        from core.config import get_settings

        cfg = get_settings()
        return IBKRConnectionConfig(
            host=host or cfg.ibkr_host,
            port=port or cfg.ibkr_port,
            client_id=client_id or cfg.ibkr_client_id,
            readonly=True,
            timeout_seconds=cfg.ibkr_timeout_seconds,
            connection_mode="LOCAL_TWS",
            display_name="cli-diagnostics",
        )
    return IBKRClient.from_settings().config


async def _load_broker_account_config(broker_account_id: str) -> Any:
    import uuid

    from broker.ibkr.client import IBKRClient
    from db.repositories import BrokerAccountRepository
    from db.session import get_session_factory

    async with get_session_factory()() as session:
        repo = BrokerAccountRepository(session)
        account = await repo.get_by_id(uuid.UUID(broker_account_id))
        if account is None:
            print(
                json.dumps({"error": f"broker_account_id {broker_account_id!r} not found"}),
                file=sys.stderr,
            )
            sys.exit(1)
        return IBKRClient.from_broker_account(account).config


def main() -> None:
    parser = argparse.ArgumentParser(
        description="IBKR connection + execution diagnostics (read-only)"
    )
    parser.add_argument("--host", help="IBKR host (default: from settings)")
    parser.add_argument("--port", type=int, help="IBKR port (default: from settings)")
    parser.add_argument("--client-id", type=int, dest="client_id", help="Client ID")
    parser.add_argument(
        "--broker-account-id",
        dest="broker_account_id",
        help="UUID of broker_account row to use (loads from DB)",
    )
    args = parser.parse_args()

    result: dict[str, Any] = {
        "connected": False,
        "host": None,
        "port": None,
        "client_id": None,
        "connection_mode": None,
        "broker_account_id": args.broker_account_id,
        "managed_accounts": [],
        "server_time": None,
        "raw_execution_count": 0,
        "mapped_execution_count": 0,
        "first_execution_at": None,
        "last_execution_at": None,
        "reqExecutions_note": (
            "reqExecutions only returns executions from the current TWS/Gateway session "
            "(since last TWS restart, not full history). "
            "0 results with a live account means no trades this session. "
            "For 12-month history, IBKR Flex Query Reports are required (future milestone)."
        ),
        "error": None,
    }

    try:
        if args.broker_account_id:
            import asyncio
            config = asyncio.run(_load_broker_account_config(args.broker_account_id))
        else:
            config = _build_config(args.host, args.port, args.client_id)

        result["host"] = config.host
        result["port"] = config.port
        result["client_id"] = config.client_id
        result["connection_mode"] = config.connection_mode
        result["broker_account_id"] = config.broker_account_id

        from broker.ibkr.sync_runner import run_diagnostics_isolated

        diag = run_diagnostics_isolated(config)
        result["connected"] = True
        result["managed_accounts"] = diag.get("managed_accounts", [])
        result["server_time"] = diag.get("server_time")
        result["raw_execution_count"] = diag.get("raw_execution_count", 0)
        result["mapped_execution_count"] = diag.get("mapped_execution_count", 0)
        result["first_execution_at"] = diag.get("first_execution_at")
        result["last_execution_at"] = diag.get("last_execution_at")

    except Exception as exc:  # noqa: BLE001
        result["error"] = str(exc)

    print(json.dumps(result, indent=2, default=str))
    sys.exit(0 if result["connected"] else 1)


if __name__ == "__main__":
    main()
