import uuid

from core.logging import bind_correlation_id, clear_correlation_id
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

HEADER = "X-Correlation-ID"


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: object) -> Response:  # type: ignore[override]
        correlation_id = request.headers.get(HEADER) or str(uuid.uuid4())
        request.state.correlation_id = correlation_id

        bind_correlation_id(correlation_id)
        try:
            response: Response = await call_next(request)  # type: ignore[operator]
        finally:
            clear_correlation_id()

        response.headers[HEADER] = correlation_id
        return response
