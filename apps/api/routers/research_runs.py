import uuid
from typing import Any

from core.logging import get_logger
from core.responses import api_response
from db.enums import ResearchRunStatus
from db.repositories import (
    RecommendationRepository,
    ResearchRunRepository,
    StrategyVersionRepository,
    WatchlistRepository,
)
from db.schemas import (
    NeutralRecommendationResponse,
    PersonalizedRecommendationResponse,
    RecommendationEvidenceResponse,
    ResearchRunCreate,
    ResearchRunRecommendationsResponse,
    ResearchRunResponse,
    RunRecommendationItem,
)
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Request
from research_graph.runner import run_research_for_run
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/research-runs", tags=["research-runs"])
logger = get_logger(__name__)


@router.post("", status_code=201)
async def create_research_run(
    body: ResearchRunCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    # 1. Resolve active strategy version
    sv_repo = StrategyVersionRepository(db)
    active_sv = await sv_repo.get_active()
    sv_id = active_sv.id if active_sv else None
    strategy_version = active_sv.version if active_sv else "v0.1.0"

    # 2. Resolve symbols: explicit override or active watchlist
    if body.symbols:
        symbols = [s.upper() for s in body.symbols]
    else:
        wl_repo = WatchlistRepository(db)
        active = await wl_repo.list_active(user_id=current_user.user_id)
        symbols = [w.symbol for w in active]

    if not symbols:
        raise HTTPException(
            status_code=422,
            detail="No symbols to research. Add to watchlist or provide symbols in the request.",
        )

    # 3. Create run record (RUNNING) + ticker records
    run_repo = ResearchRunRepository(db)
    run = await run_repo.create(
        run_type=body.run_type,
        strategy_version_id=sv_id,
        user_id=current_user.user_id,
    )
    await run_repo.update_status(run.id, ResearchRunStatus.RUNNING)
    tickers = await run_repo.add_tickers(run.id, symbols)
    await db.commit()

    # Refresh run object after status update
    loaded_run = await run_repo.get_by_id(run.id, user_id=current_user.user_id)
    if loaded_run is None:
        raise HTTPException(status_code=500, detail="Failed to load run after creation")

    logger.info("research_run_started", run_id=str(run.id), symbols=symbols)

    # 4. Execute research graph for every ticker
    try:
        summary = await run_research_for_run(loaded_run, tickers, db, strategy_version)
        final_status = (
            ResearchRunStatus.COMPLETED
            if not summary["symbols_failed"]
            else ResearchRunStatus.FAILED
        )
    except Exception as exc:
        logger.error("research_run_graph_error", run_id=str(run.id), error=str(exc))
        summary = {"symbols_failed": symbols, "errors": [str(exc)]}
        final_status = ResearchRunStatus.FAILED

    # 5. Mark run complete and commit everything
    await run_repo.update_status(run.id, final_status)
    await db.commit()

    # 6. Reload with fresh tickers for response
    final_run = await run_repo.get_by_id(run.id, user_id=current_user.user_id)
    if final_run is None:
        raise HTTPException(status_code=500, detail="Failed to reload completed run")

    logger.info(
        "research_run_completed",
        run_id=str(run.id),
        status=final_status.value,
        completed=summary.get("symbols_completed", []),
        failed=summary.get("symbols_failed", []),
    )
    return api_response(ResearchRunResponse.model_validate(final_run).model_dump(), request)


@router.get("")
async def list_research_runs(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    repo = ResearchRunRepository(db)
    runs = await repo.list_recent(
        limit=min(limit, 100),
        offset=offset,
        user_id=current_user.user_id,
    )
    items = [
        {
            "id": str(r.id),
            "run_type": r.run_type,
            "status": r.status,
            "created_at": r.created_at.isoformat(),
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in runs
    ]
    return api_response(items, request)


@router.get("/{run_id}")
async def get_research_run(
    run_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    repo = ResearchRunRepository(db)
    run = await repo.get_by_id(run_id, user_id=current_user.user_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Research run {run_id} not found")
    return api_response(ResearchRunResponse.model_validate(run).model_dump(), request)


@router.get("/{run_id}/recommendations")
async def get_run_recommendations(
    run_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    run_repo = ResearchRunRepository(db)
    run = await run_repo.get_by_id(run_id, user_id=current_user.user_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Research run {run_id} not found")

    rec_repo = RecommendationRepository(db)
    neutrals = await rec_repo.get_neutral_by_run_id(run_id)

    items: list[RunRecommendationItem] = []
    if neutrals:
        neutral_ids = [n.id for n in neutrals]
        personalized_by_neutral = await rec_repo.get_latest_personalized_by_neutral_ids(
            neutral_ids
        )
        evidence_by_neutral = await rec_repo.get_evidence_by_neutral_ids(neutral_ids)

        for n in neutrals:
            pers = personalized_by_neutral.get(n.id)
            ev_rows = evidence_by_neutral.get(n.id, [])
            items.append(
                RunRecommendationItem(
                    symbol=n.symbol,
                    neutral=NeutralRecommendationResponse.model_validate(n),
                    personalized=(
                        PersonalizedRecommendationResponse.model_validate(pers) if pers else None
                    ),
                    evidence=[
                        RecommendationEvidenceResponse.model_validate(e) for e in ev_rows
                    ],
                )
            )

    payload = ResearchRunRecommendationsResponse(
        research_run_id=run.id,
        status=run.status,
        run_type=run.run_type,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        recommendations=items,
    )
    return api_response(payload.model_dump(), request)
