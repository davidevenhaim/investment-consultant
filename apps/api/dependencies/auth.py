"""Minimal development user context for M10.1.

This is intentionally not production auth. It gives API routes a stable
request-level user id so data ownership can be enforced during development.
"""

import uuid

from fastapi import HTTPException, Request
from pydantic import BaseModel

DEV_DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
USER_ID_HEADER = "x-user-id"


class CurrentUser(BaseModel):
    user_id: uuid.UUID


async def get_current_user(request: Request) -> CurrentUser:
    raw_user_id = request.headers.get(USER_ID_HEADER)
    if not raw_user_id:
        return CurrentUser(user_id=DEV_DEFAULT_USER_ID)

    try:
        user_id = uuid.UUID(raw_user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid X-User-Id header.") from exc

    return CurrentUser(user_id=user_id)
