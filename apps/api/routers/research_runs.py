import uuid
import uuid as uuid_mod
from typing import Any

from core.logging import get_logger
from core.responses import api_response
from db.enums import ResearchRunStatus, ResearchRunType
from db.repositories import (
    BrokerAccountRepository,
    RecommendationRepository,
    ResearchRunRepository,
    StrategyVersionRepository,
    WatchlistRepository,
)
from db.schemas import (
    HistoricalReplayRequest,
    NeutralRecommendationResponse,
    PersonalizedRecommendationResponse,
    RecommendationEvidenceResponse,
    ResearchRunCreate,
    ResearchRunRecommendationsResponse,
    ResearchRunResponse,
    RunRecommendationItem,
    _generate_replay_dates,
)
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Request
from research_graph.runner import run_research_for_run
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies.auth import CurrentUser, get_current_user

# Dispatch via celery_app.send_task() — NOT task.delay() — so the configured
# broker URL (Redis) is always used, regardless of Celery's "current app" in
# this process.  Importing the task object directly and calling .delay() routes
# through whatever default Celery app is active at import time, which may not
# have the correct broker when running in the API process.
from apps.worker.celery_app import celery_app as _celery_app
from apps.worker.tasks.research import RUN_RESEARCH_RUN_TASK_NAME

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

    # 3. Create run record + ticker records
    run_repo = ResearchRunRepository(db)
    run = await run_repo.create(
        run_type=body.run_type,
        strategy_version_id=sv_id,
        user_id=current_user.user_id,
    )

    # ── Async path: enqueue and return immediately ─────────────────────────
    if body.async_execution:
        await run_repo.update_status(run.id, ResearchRunStatus.QUEUED)
        await run_repo.add_tickers(run.id, symbols)
        await db.commit()

        queued_run = await run_repo.get_by_id(run.id, user_id=current_user.user_id)
        if queued_run is None:
            raise HTTPException(status_code=500, detail="Failed to load queued run")

        # Resolve broker account before closing session
        ba_repo = BrokerAccountRepository(db)
        broker_account = await ba_repo.get_active_default(user_id=current_user.user_id)
        broker_account_id_str = str(broker_account.id) if broker_account else None

        try:
            _celery_app.send_task(
                RUN_RESEARCH_RUN_TASK_NAME,
                args=[str(run.id), str(current_user.user_id), broker_account_id_str],
            )
        except Exception as exc:
            logger.error(
                "research_run_enqueue_failed",
                run_id=str(run.id),
                error=type(exc).__name__,
            )
            # Mark the run FAILED so it does not sit as QUEUED forever
            await run_repo.update_status(
                run.id, ResearchRunStatus.FAILED, error_message="Job queue unavailable"
            )
            await db.commit()
            raise HTTPException(
                status_code=503,
                detail="Research job queue is unavailable. Please retry.",
            ) from None

        logger.info(
            "research_run_enqueued",
            run_id=str(run.id),
            symbols=symbols,
        )
        return api_response(ResearchRunResponse.model_validate(queued_run).model_dump(), request)

    # ── Sync path: existing behavior (default) ────────────────────────────
    await run_repo.update_status(run.id, ResearchRunStatus.RUNNING)
    tickers = await run_repo.add_tickers(run.id, symbols)
    await db.commit()

    # Refresh run object after status update
    loaded_run = await run_repo.get_by_id(run.id, user_id=current_user.user_id)
    if loaded_run is None:
        raise HTTPException(status_code=500, detail="Failed to load run after creation")

    logger.info("research_run_started", run_id=str(run.id), symbols=symbols)

    ba_repo = BrokerAccountRepository(db)
    broker_account = await ba_repo.get_active_default(user_id=current_user.user_id)
    broker_account_id = broker_account.id if broker_account is not None else None

    # 4. Execute research graph for every ticker
    try:
        summary = await run_research_for_run(
            loaded_run,
            tickers,
            db,
            strategy_version,
            broker_account_id=broker_account_id,
            enforce_broker_scope=True,
        )
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
        personalized_by_neutral = await rec_repo.get_latest_personalized_by_neutral_ids(neutral_ids)
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
                    evidence=[RecommendationEvidenceResponse.model_validate(e) for e in ev_rows],
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


@router.post("/historical-replay", status_code=201)
async def create_historical_replay(
    body: HistoricalReplayRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Create a batch of historical replay research runs.

    Generates one ResearchRun per cadence date between start_date and end_date.
    Each run is enqueued as a Celery task (always async). Runs are tagged with
    metadata_json.historical_replay=true and metadata_json.as_of_date.

    Replay runs are classified as REAL (not SCENARIO) for advisor backtest source
    filtering. Use recommendation_source=REAL to include them in backtests.
    """
    symbols = [s.upper() for s in body.symbols]
    replay_dates = _generate_replay_dates(body.start_date, body.end_date, body.cadence)
    replay_batch_id = str(uuid_mod.uuid4())

    sv_repo = StrategyVersionRepository(db)
    active_sv = await sv_repo.get_active()
    sv_id = active_sv.id if active_sv else None

    run_repo = ResearchRunRepository(db)
    created_runs: list[dict[str, Any]] = []

    for replay_date in replay_dates:
        run = await run_repo.create(
            run_type=ResearchRunType.HISTORICAL_REPLAY,
            strategy_version_id=sv_id,
            user_id=current_user.user_id,
        )
        await run_repo.update_status(run.id, ResearchRunStatus.QUEUED)
        await run_repo.add_tickers(run.id, symbols)

        # Tag run with replay metadata — no scenario_seed so REAL filter includes it
        from db.models import ResearchRun as ResearchRunModel  # noqa: PLC0415
        from sqlalchemy import update as sa_update  # noqa: PLC0415

        await db.execute(
            sa_update(ResearchRunModel)
            .where(ResearchRunModel.id == run.id)
            .values(
                metadata_json={
                    "historical_replay": True,
                    "replay_batch_id": replay_batch_id,
                    "as_of_date": replay_date.isoformat(),
                    "source": "historical_graph_replay",
                    "cadence": body.cadence,
                }
            )
        )

        created_runs.append(
            {
                "id": str(run.id),
                "as_of_date": replay_date.isoformat(),
                "status": ResearchRunStatus.QUEUED.value,
                "symbols": symbols,
            }
        )

    await db.commit()

    # Enqueue all runs after committing so the worker can load them
    ba_repo = BrokerAccountRepository(db)
    broker_account = await ba_repo.get_active_default(user_id=current_user.user_id)
    broker_account_id_str = str(broker_account.id) if broker_account else None

    enqueued_ids: list[str] = []
    try:
        for run_info in created_runs:
            _celery_app.send_task(
                RUN_RESEARCH_RUN_TASK_NAME,
                args=[run_info["id"], str(current_user.user_id), broker_account_id_str],
            )
            enqueued_ids.append(run_info["id"])
    except Exception as exc:
        logger.error(
            "historical_replay_enqueue_failed",
            replay_batch_id=replay_batch_id,
            enqueued=len(enqueued_ids),
            total=len(created_runs),
            error=type(exc).__name__,
        )
        # Mark all un-enqueued runs as FAILED so they don't sit QUEUED forever
        from db.models import ResearchRun as _ResearchRunModel  # noqa: PLC0415
        from sqlalchemy import update as _sa_update  # noqa: PLC0415

        failed_ids = [r["id"] for r in created_runs if r["id"] not in enqueued_ids]
        if failed_ids:
            await db.execute(
                _sa_update(_ResearchRunModel)
                .where(_ResearchRunModel.id.in_([uuid_mod.UUID(fid) for fid in failed_ids]))
                .values(
                    status=ResearchRunStatus.FAILED.value,
                    error_message="Job queue unavailable",
                )
            )
            await db.commit()
        raise HTTPException(
            status_code=503,
            detail="Research job queue is unavailable. Please retry.",
        ) from None

    logger.info(
        "historical_replay_batch_created",
        replay_batch_id=replay_batch_id,
        count=len(created_runs),
        start_date=str(body.start_date),
        end_date=str(body.end_date),
        cadence=body.cadence,
        symbols=symbols,
    )

    return api_response(
        {
            "replay_batch_id": replay_batch_id,
            "count": len(created_runs),
            "runs": created_runs,
        },
        request,
    )
