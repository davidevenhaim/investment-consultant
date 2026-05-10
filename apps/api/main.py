import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from core.config import get_settings
from core.errors import InvestmentConsultantError
from core.logging import get_logger, setup_logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from apps.api.middleware.correlation import CorrelationIDMiddleware
from apps.api.routers import (
    fundamentals,
    health,
    market_data,
    memory,
    news,
    portfolio,
    recommendations,
    research_runs,
    risk_profile,
    watchlist,
)

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    setup_logging(settings.log_level)
    from db.session import init_db

    init_db(settings.database_url)
    logger.info("api_starting", environment=settings.environment, version="0.1.0")
    yield
    logger.info("api_stopping")


app = FastAPI(
    title="Investment Research API",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(InvestmentConsultantError)
async def app_error_handler(request: Request, exc: InvestmentConsultantError) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    logger.error(
        "application_error",
        error_code=exc.error_code,
        message=exc.message,
        status_code=exc.status_code,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {"code": exc.error_code, "message": exc.message, "detail": exc.detail},
            "meta": {"request_id": correlation_id},
        },
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    correlation_id = getattr(request.state, "correlation_id", str(uuid.uuid4()))
    logger.error("unhandled_error", error=str(exc), exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "An unexpected error occurred.",
                "detail": {},
            },
            "meta": {"request_id": correlation_id},
        },
    )


app.include_router(health.router, prefix="/api/v1")
app.include_router(watchlist.router, prefix="/api/v1")
app.include_router(risk_profile.router, prefix="/api/v1")
app.include_router(research_runs.router, prefix="/api/v1")
app.include_router(recommendations.router, prefix="/api/v1")
app.include_router(market_data.router, prefix="/api/v1")
app.include_router(fundamentals.router, prefix="/api/v1")
app.include_router(memory.router, prefix="/api/v1")
app.include_router(news.router, prefix="/api/v1")
app.include_router(portfolio.router, prefix="/api/v1")


@app.get("/", include_in_schema=False)
async def root() -> dict[str, Any]:
    return {"service": "investment-research-api", "version": "0.1.0", "docs": "/api/docs"}
