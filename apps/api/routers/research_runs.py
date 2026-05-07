import uuid
from typing import Any

from core.logging import get_logger
from core.responses import api_response
from db.repositories import ResearchRunRepository, StrategyVersionRepository, WatchlistRepository
from db.schemas import ResearchRunCreate, ResearchRunResponse
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/research-runs", tags=["research-runs"])
logger = get_logger(__name__)


@router.post("", status_code=201)
async def create_research_run(
    body: ResearchRunCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    sv_repo = StrategyVersionRepository(db)
    active_sv = await sv_repo.get_active()
    sv_id = active_sv.id if active_sv else None

    if body.symbols:
        symbols = [s.upper() for s in body.symbols]
    else:
        wl_repo = WatchlistRepository(db)
        active = await wl_repo.list_active()
        symbols = [w.symbol for w in active]

    if not symbols:
        raise HTTPException(
            status_code=422,
            detail="No symbols to research. Add to watchlist or provide symbols in the request.",
        )

    run_repo = ResearchRunRepository(db)
    run = await run_repo.create(run_type=body.run_type, strategy_version_id=sv_id)
    await run_repo.add_tickers(run.id, symbols)
    await db.commit()

    # Reload to hydrate the tickers relationship
    loaded = await run_repo.get_by_id(run.id)
    if loaded is None:
        raise HTTPException(status_code=500, detail="Failed to reload run after creation")

    logger.info("research_run_created", run_id=str(loaded.id), run_type=loaded.run_type,
               symbols=symbols)
    return api_response(ResearchRunResponse.model_validate(loaded).model_dump(), request)


@router.get("")
async def list_research_runs(
    request: Request,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    repo = ResearchRunRepository(db)
    runs = await repo.list_recent(limit=min(limit, 100), offset=offset)
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
) -> dict[str, Any]:
    repo = ResearchRunRepository(db)
    run = await repo.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"Research run {run_id} not found")
    return api_response(ResearchRunResponse.model_validate(run).model_dump(), request)
