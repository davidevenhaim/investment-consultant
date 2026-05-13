"""Backtesting router — M11 outcome measurement + learning event management."""

from typing import Any

from backtesting.repository import LearningEventRepository, RecommendationOutcomeRepository
from backtesting.service import measure_latest_recommendations
from core.responses import api_response
from db.schemas import (
    LearningEventResponse,
    LearningEventStatusUpdate,
    MeasureOutcomesRequest,
    RecommendationOutcomeResponse,
)
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

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
