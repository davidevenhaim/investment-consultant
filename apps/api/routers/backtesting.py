"""Backtesting router — M11 outcome measurement + learning events + advisor simulation."""

import uuid as _uuid
from typing import Any

from backtesting.advisor_simulation import run_advisor_backtest
from backtesting.repository import LearningEventRepository, RecommendationOutcomeRepository
from backtesting.service import measure_latest_recommendations
from core.responses import api_response
from db.models import AdvisorBacktestRun
from db.schemas import (
    AdvisorBacktestRequest,
    AdvisorBacktestRunDetailResponse,
    AdvisorBacktestRunResponse,
    LearningEventResponse,
    LearningEventStatusUpdate,
    MeasureOutcomesRequest,
    RecommendationOutcomeResponse,
)
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from apps.api.dependencies.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/backtesting", tags=["backtesting"])


@router.post("/outcomes/measure-latest")
async def measure_latest(
    body: MeasureOutcomesRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Measure forward outcomes for the current user's latest completed research run.

    If the horizon has not elapsed or price data is insufficient, rows are
    returned with outcome_status=INSUFFICIENT_DATA — not an error.
    """
    outcomes = await measure_latest_recommendations(
        session=db,
        user_id=current_user.user_id,
        horizon_days=body.horizon_days,
        benchmark_symbol=body.benchmark_symbol,
    )
    await db.commit()

    if not outcomes:
        return api_response(
            {"outcomes": [], "message": "No completed research run found for this user."},
            request,
        )

    rows = [RecommendationOutcomeResponse.model_validate(o).model_dump() for o in outcomes]
    return api_response({"outcomes": rows, "count": len(rows)}, request)


@router.get("/outcomes")
async def list_outcomes(
    request: Request,
    symbol: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return recent recommendation outcomes for the current user."""
    repo = RecommendationOutcomeRepository(db)
    rows = await repo.list_for_user(
        user_id=current_user.user_id,
        symbol=symbol,
        status=status,
        limit=limit,
    )
    data = [RecommendationOutcomeResponse.model_validate(r).model_dump() for r in rows]
    return api_response(data, request)


@router.get("/learning-events")
async def list_learning_events(
    request: Request,
    symbol: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return learning events for the current user."""
    repo = LearningEventRepository(db)
    rows = await repo.list_for_user(
        user_id=current_user.user_id,
        symbol=symbol,
        status=status,
        limit=limit,
    )
    data = [LearningEventResponse.model_validate(r).model_dump() for r in rows]
    return api_response(data, request)


@router.post("/learning-events/{event_id}/review")
async def review_learning_event(
    event_id: str,
    body: LearningEventStatusUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Update a learning event status (REVIEWED / DISMISSED / APPLIED).

    Returns 404 if the event does not belong to the current user.
    """
    import uuid as _uuid

    try:
        eid = _uuid.UUID(event_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid event_id UUID.") from exc

    repo = LearningEventRepository(db)
    updated = await repo.update_status(eid, current_user.user_id, body.status)
    if updated is None:
        raise HTTPException(status_code=404, detail="Learning event not found.")

    await db.commit()
    return api_response(LearningEventResponse.model_validate(updated).model_dump(), request)


# ── Advisor backtest (M11.1) ──────────────────────────────────────────────────


@router.post("/advisor-runs", status_code=201)
async def create_advisor_backtest(
    body: AdvisorBacktestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Run a follow-the-advisor simulation for the current user.

    Uses only the user's own completed research runs within the date range.
    Missing price data is handled gracefully — no 500.
    """
    run = await run_advisor_backtest(
        session=db,
        user_id=current_user.user_id,
        start_date=body.start_date,
        end_date=body.end_date,
        initial_cash=body.initial_cash,
        benchmark_symbol=body.benchmark_symbol,
        name=body.name,
    )
    await db.commit()

    # Reload with relationships for detail response
    result = await db.execute(
        select(AdvisorBacktestRun)
        .options(
            selectinload(AdvisorBacktestRun.trades),
            selectinload(AdvisorBacktestRun.equity_points),
        )
        .where(AdvisorBacktestRun.id == run.id)
    )
    run_full = result.scalar_one()
    return api_response(
        AdvisorBacktestRunDetailResponse.model_validate(run_full).model_dump(), request
    )


@router.get("/advisor-runs")
async def list_advisor_backtests(
    request: Request,
    status: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """List advisor backtest runs for the current user."""
    q = (
        select(AdvisorBacktestRun)
        .where(AdvisorBacktestRun.user_id == current_user.user_id)
        .order_by(AdvisorBacktestRun.created_at.desc())
        .limit(limit)
    )
    if status:
        q = q.where(AdvisorBacktestRun.status == status.upper())
    result = await db.execute(q)
    rows = result.scalars().all()
    data = [AdvisorBacktestRunResponse.model_validate(r).model_dump() for r in rows]
    return api_response(data, request)


@router.get("/advisor-runs/{run_id}")
async def get_advisor_backtest(
    run_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return a single advisor backtest run with trades and equity curve.

    Returns 404 if not found or belongs to a different user.
    """
    try:
        rid = _uuid.UUID(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid run_id UUID.") from exc

    result = await db.execute(
        select(AdvisorBacktestRun)
        .options(
            selectinload(AdvisorBacktestRun.trades),
            selectinload(AdvisorBacktestRun.equity_points),
        )
        .where(
            AdvisorBacktestRun.id == rid,
            AdvisorBacktestRun.user_id == current_user.user_id,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Advisor backtest run not found.")

    return api_response(
        AdvisorBacktestRunDetailResponse.model_validate(run).model_dump(), request
    )
