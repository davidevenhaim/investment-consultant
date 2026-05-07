import asyncio
import time
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import chromadb
import redis.asyncio as aioredis
from core.config import Settings, get_settings
from core.logging import get_logger
from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

router = APIRouter(tags=["health"])
logger = get_logger(__name__)

OverallStatus = Literal["ok", "degraded", "error"]


class ServiceHealth(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: float | None = None
    message: str | None = None


class DetailedHealthResponse(BaseModel):
    status: OverallStatus
    version: str = "0.1.0"
    services: dict[str, ServiceHealth]


def _meta(request: Request) -> dict[str, str]:
    return {
        "request_id": getattr(request.state, "correlation_id", str(uuid.uuid4())),
        "timestamp": datetime.now(UTC).isoformat(),
    }


async def _check_postgres(settings: Settings) -> ServiceHealth:
    t0 = time.monotonic()
    try:
        engine = create_async_engine(settings.database_url, pool_size=1, max_overflow=0)
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        await engine.dispose()
        return ServiceHealth(status="ok", latency_ms=round((time.monotonic() - t0) * 1000, 1))
    except Exception as exc:
        logger.warning("postgres_health_check_failed", error=str(exc))
        return ServiceHealth(status="error", message=str(exc))


async def _check_redis(settings: Settings) -> ServiceHealth:
    t0 = time.monotonic()
    try:
        r = aioredis.from_url(settings.redis_url, socket_connect_timeout=3)  # type: ignore[no-untyped-call]
        await r.ping()
        await r.aclose()
        return ServiceHealth(status="ok", latency_ms=round((time.monotonic() - t0) * 1000, 1))
    except Exception as exc:
        logger.warning("redis_health_check_failed", error=str(exc))
        return ServiceHealth(status="error", message=str(exc))


async def _check_chroma(settings: Settings) -> ServiceHealth:
    t0 = time.monotonic()
    try:
        client = chromadb.HttpClient(host=settings.chroma_host, port=settings.chroma_port)
        await asyncio.get_event_loop().run_in_executor(None, client.heartbeat)
        return ServiceHealth(status="ok", latency_ms=round((time.monotonic() - t0) * 1000, 1))
    except Exception as exc:
        logger.warning("chroma_health_check_failed", error=str(exc))
        return ServiceHealth(status="error", message=str(exc))


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    return {
        "data": {"status": "ok", "version": "0.1.0"},
        "meta": _meta(request),
    }


@router.get("/health/detailed")
async def health_detailed(request: Request) -> dict[str, Any]:
    settings = get_settings()

    postgres_health, redis_health, chroma_health = await asyncio.gather(
        _check_postgres(settings),
        _check_redis(settings),
        _check_chroma(settings),
        return_exceptions=False,
    )

    services = {
        "postgres": postgres_health,
        "redis": redis_health,
        "chroma": chroma_health,
    }

    all_ok = all(s.status == "ok" for s in services.values())
    any_error = any(s.status == "error" for s in services.values())
    overall: OverallStatus = "ok" if all_ok else ("error" if any_error else "degraded")

    response = DetailedHealthResponse(status=overall, services=services)

    return {
        "data": response.model_dump(),
        "meta": _meta(request),
    }
