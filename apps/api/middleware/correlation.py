"""Pure ASGI correlation ID middleware — avoids BaseHTTPMiddleware event loop issues."""
import uuid
from typing import Any

from core.logging import bind_correlation_id, clear_correlation_id

HEADER_NAME = b"x-correlation-id"


class CorrelationIDMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        raw_headers: list[tuple[bytes, bytes]] = scope.get("headers", [])
        correlation_id = next(
            (v.decode() for k, v in raw_headers if k.lower() == HEADER_NAME),
            str(uuid.uuid4()),
        )
        scope["state"] = scope.get("state", {})
        scope["state"]["correlation_id"] = correlation_id
        bind_correlation_id(correlation_id)

        async def send_with_header(message: Any) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((HEADER_NAME, correlation_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            clear_correlation_id()
