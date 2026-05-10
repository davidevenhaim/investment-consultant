"""IBKR async context-manager client — read-only, never submits orders."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from core.config import get_settings
from core.errors import IBKRConnectionError, IBKRReadOnlyError

logger = logging.getLogger(__name__)


class IBKRClient:
    """Thin wrapper around ib_insync.IB for read-only access.

    Always use as an async context manager:
        async with IBKRClient() as client:
            executions = await client.fetch_executions(months=12)
    """

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        client_id: int | None = None,
        timeout: int | None = None,
        readonly: bool = True,
    ) -> None:
        cfg = get_settings()
        self._host = host or cfg.ibkr_host
        self._port = port or cfg.ibkr_port
        self._client_id = client_id or cfg.ibkr_client_id
        self._timeout = timeout or cfg.ibkr_timeout_seconds
        self._readonly = readonly
        self._ib: object | None = None

    # ── read-only guard ───────────────────────────────────────────────────────

    def _assert_readonly(self, operation: str) -> None:
        if self._readonly:
            raise IBKRReadOnlyError(
                f"IBKR client is read-only. Refusing operation: {operation}"
            )

    # ── connection lifecycle ──────────────────────────────────────────────────

    async def connect(self) -> None:
        try:
            import ib_insync  # noqa: PLC0415 — optional dep

            ib = ib_insync.IB()
            await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: ib.connect(
                        self._host, self._port, clientId=self._client_id, readonly=self._readonly
                    ),
                ),
                timeout=self._timeout,
            )
            self._ib = ib
            logger.info("ibkr_connected", extra={"host": self._host, "port": self._port})
        except ImportError as exc:
            raise IBKRConnectionError("ib_insync not installed") from exc
        except TimeoutError as exc:
            raise IBKRConnectionError(
                f"IBKR connection timed out after {self._timeout}s"
            ) from exc
        except Exception as exc:
            raise IBKRConnectionError(f"IBKR connection failed: {exc}") from exc

    async def disconnect(self) -> None:
        if self._ib is not None:
            try:
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self._ib.disconnect)  # type: ignore[attr-defined]
            except Exception as exc:  # noqa: BLE001
                logger.debug("ibkr_disconnect_error", extra={"error": str(exc)})
            self._ib = None
            logger.info("ibkr_disconnected")

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

    async def account_id(self) -> str:
        loop = asyncio.get_event_loop()
        accounts = await loop.run_in_executor(
            None, lambda: self.ib.managedAccounts()  # type: ignore[attr-defined]
        )
        return str(accounts[0]) if accounts else ""
