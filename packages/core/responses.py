import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import Request


def api_response(data: Any, request: Request | None = None) -> dict[str, Any]:
    request_id = str(uuid.uuid4())
    if request is not None:
        request_id = getattr(request.state, "correlation_id", request_id)
    return {
        "data": data,
        "meta": {
            "request_id": request_id,
            "timestamp": datetime.now(UTC).isoformat(),
        },
    }
