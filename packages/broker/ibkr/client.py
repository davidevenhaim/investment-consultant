"""IBKR async context-manager client — read-only, never submits orders."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from db.models import BrokerAccount

from core.config import get_settings
from core.errors import IBKRConnectionError, IBKRReadOnlyError

logger = logging.getLogger(__name__)

ConnectionMode = Literal["LOCAL_TWS", "HOSTED_GATEWAY"]


@dataclass
class IBKRConnectionConfig:
    host: str
    port: int
    client_id: int
    readonly: bool
    timeout_seconds: int
    connection_mode: ConnectionMode = "LOCAL_TWS"
    broker_account_id: str | None = None
    display_name: str = field(default="default")


class IBKRClient:
    """Read-only ib_insync wrapper. Always use via connected() context manager.

    async with IBKRClient.from_settings().connected() as client:
        executions = await fetch_executions(client, months=12)
    """

    def __init__(self, config: IBKRConnectionConfig) -> None:
        if not config.readonly:
            raise IBKRReadOnlyError(
                "IBKR client must be read-only. Set readonly=True in IBKRConnectionConfig."
            )
        self._cfg = config
        self._ib: object | None = None

    # ── factory constructors ──────────────────────────────────────────────────

    @classmethod
    def from_settings(cls) -> IBKRClient:
        """Build from global Settings (dev / single-account use)."""
        cfg = get_settings()
        return cls(
            IBKRConnectionConfig(
                host=cfg.ibkr_host,
                port=cfg.ibkr_port,
                client_id=cfg.ibkr_client_id,
                readonly=cfg.ibkr_readonly,
                timeout_seconds=cfg.ibkr_timeout_seconds,
                connection_mode="LOCAL_TWS",
                display_name="settings-default",
            )
        )

    @classmethod
    def from_broker_account(cls, account: BrokerAccount) -> IBKRClient:
        """Build from a BrokerAccount DB record."""
        cfg = get_settings()

        mode: ConnectionMode = (
            "HOSTED_GATEWAY" if str(account.connection_mode) == "HOSTED_GATEWAY" else "LOCAL_TWS"
        )

        if mode == "HOSTED_GATEWAY":
            if not account.host or not account.port:
                raise IBKRConnectionError(
                    f"BrokerAccount {account.id} is HOSTED_GATEWAY but missing host/port. "
                    "Set host and port on the broker account."
                )
            host = str(account.host)
            port = int(account.port)
        else:
            # LOCAL_TWS: use account config if present, else fall back to settings
            host = str(account.host) if account.host else cfg.ibkr_host
            port = int(account.port) if account.port else cfg.ibkr_port

        client_id = int(account.client_id) if account.client_id is not None else cfg.ibkr_client_id
        readonly = bool(account.readonly)
        timeout = cfg.ibkr_timeout_seconds

        return cls(
            IBKRConnectionConfig(
                host=host,
                port=port,
                client_id=client_id,
                readonly=readonly,
                timeout_seconds=timeout,
                connection_mode=mode,
                broker_account_id=str(account.id),
                display_name=str(account.display_name),
            )
        )

    # ── connection lifecycle ──────────────────────────────────────────────────

    async def connect(self) -> None:
        cfg = self._cfg
        logger.info(
            "ibkr_connect_attempt",
            extra={
                "host": cfg.host,
                "port": cfg.port,
                "client_id": cfg.client_id,
                "connection_mode": cfg.connection_mode,
                "broker_account_id": cfg.broker_account_id,
                "display_name": cfg.display_name,
            },
        )
        try:
            from ib_insync import IB  # noqa: PLC0415 — optional dep

            ib = IB()
            await asyncio.wait_for(
                ib.connectAsync(
                    cfg.host,
                    cfg.port,
                    clientId=cfg.client_id,
                    readonly=cfg.readonly,
                ),
                timeout=cfg.timeout_seconds,
            )
            self._ib = ib
            logger.info(
                "ibkr_connected",
                extra={
                    "host": cfg.host,
                    "port": cfg.port,
                    "broker_account_id": cfg.broker_account_id,
                },
            )
        except ImportError as exc:
            logger.error("ibkr_connection_failed", extra={"reason": "ib_insync not installed"})
            raise IBKRConnectionError("ib_insync not installed") from exc
        except TimeoutError as exc:
            logger.error(
                "ibkr_connection_failed",
                extra={"reason": "timeout", "timeout_seconds": cfg.timeout_seconds},
            )
            raise IBKRConnectionError(
                f"IBKR connection timed out after {cfg.timeout_seconds}s ({cfg.host}:{cfg.port})"
            ) from exc
        except (IBKRConnectionError, IBKRReadOnlyError):
            raise
        except Exception as exc:
            logger.error(
                "ibkr_connection_failed",
                extra={"reason": str(exc), "host": cfg.host, "port": cfg.port},
            )
            raise IBKRConnectionError(
                f"IBKR connection failed ({cfg.host}:{cfg.port}): {exc}"
            ) from exc

    async def disconnect(self) -> None:
        if self._ib is not None:
            try:
                self._ib.disconnect()  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                logger.debug("ibkr_disconnect_error", extra={"error": str(exc)})
            self._ib = None
            logger.info(
                "ibkr_disconnected",
                extra={"broker_account_id": self._cfg.broker_account_id},
            )

    @asynccontextmanager
    async def connected(self) -> AsyncIterator[IBKRClient]:
        await self.connect()
        try:
            yield self
        finally:
            await self.disconnect()

    # ── data access ───────────────────────────────────────────────────────────

    @property
    def ib(self) -> object:
        if self._ib is None:
            raise IBKRConnectionError("Not connected. Use `async with client.connected()`.")
        return self._ib

    @property
    def config(self) -> IBKRConnectionConfig:
        return self._cfg

    @property
    def broker_account_id(self) -> str | None:
        return self._cfg.broker_account_id

    async def account_id(self) -> str:
        accounts = self.ib.managedAccounts()  # type: ignore[attr-defined]
        return str(accounts[0]) if accounts else ""
