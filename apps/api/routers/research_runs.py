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
    AdvisorBacktestRunDetailResponse,
    HistoricalReplayRequest,
    NeutralRecommendationResponse,
    PersonalizedRecommendationResponse,
    RecommendationEvidenceResponse,
    ReplayBatchBacktestRequest,
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


@router.get("/historical-replay/{replay_batch_id}")
async def get_replay_batch_status(
    replay_batch_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return status of every run in a historical replay batch.

    Returns 404 if the batch does not exist or belongs to a different user.
    Runs are ordered by as_of_date ascending.
    """
    repo = ResearchRunRepository(db)
    runs = await repo.get_by_replay_batch_id(replay_batch_id, current_user.user_id)
    if not runs:
        raise HTTPException(status_code=404, detail=f"Replay batch {replay_batch_id} not found.")

    counts: dict[str, int] = {}
    for r in runs:
        counts[r.status] = counts.get(r.status, 0) + 1

    terminal_statuses = {"COMPLETED", "FAILED", "CANCELLED"}
    terminal_count = sum(counts.get(s, 0) for s in terminal_statuses)
    total = len(runs)
    progress_pct = round(terminal_count / total * 100, 1) if total else 0.0

    as_of_dates: list[str] = [
        str(r.metadata_json["as_of_date"]) for r in runs if r.metadata_json.get("as_of_date")
    ]
    started_ats = [r.started_at for r in runs if r.started_at is not None]
    finished_ats = [r.finished_at for r in runs if r.finished_at is not None]

    earliest_started = min(started_ats) if started_ats else None
    latest_finished = max(finished_ats) if finished_ats else None

    elapsed_seconds: float | None = None
    if earliest_started is not None:
        import datetime as _dt  # noqa: PLC0415
        from datetime import UTC  # noqa: PLC0415

        if latest_finished is not None:
            # Replay runs have backdated finished_at — guard against negative duration.
            delta = (latest_finished - earliest_started).total_seconds()
            elapsed_seconds = round(delta, 1) if delta >= 0 else None
        else:
            elapsed_seconds = round((_dt.datetime.now(UTC) - earliest_started).total_seconds(), 1)

    run_items = [
        {
            "id": str(r.id),
            "as_of_date": r.metadata_json.get("as_of_date"),
            "status": r.status,
            "symbols": [t.symbol for t in r.tickers],
            "created_at": r.created_at.isoformat(),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
        }
        for r in runs
    ]

    return api_response(
        {
            "replay_batch_id": replay_batch_id,
            "total": total,
            "completed_count": counts.get("COMPLETED", 0),
            "failed_count": counts.get("FAILED", 0),
            "running_count": counts.get("RUNNING", 0),
            "queued_count": counts.get("QUEUED", 0),
            "progress_pct": progress_pct,
            "first_as_of_date": min(as_of_dates) if as_of_dates else None,
            "last_as_of_date": max(as_of_dates) if as_of_dates else None,
            "started_at": earliest_started.isoformat() if earliest_started else None,
            "finished_at": latest_finished.isoformat() if latest_finished else None,
            "elapsed_seconds": elapsed_seconds,
            # kept for backwards compatibility
            "counts": counts,
            "runs": run_items,
        },
        request,
    )


@router.post("/historical-replay/{replay_batch_id}/backtest", status_code=201)
async def create_replay_batch_backtest(
    replay_batch_id: str,
    body: ReplayBatchBacktestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Run an advisor backtest over a completed historical replay batch.

    Uses only the COMPLETED runs in the batch as the recommendation source.
    The date window is derived from the batch's min/max as_of_date values.
    Returns 404 if the batch does not exist for this user.
    Returns 422 if none of the batch runs are COMPLETED.
    """
    import datetime as _dt  # noqa: PLC0415

    from backtesting.advisor_simulation import run_advisor_backtest  # noqa: PLC0415
    from db.models import AdvisorBacktestRun  # noqa: PLC0415
    from sqlalchemy import select  # noqa: PLC0415
    from sqlalchemy.orm import selectinload  # noqa: PLC0415

    repo = ResearchRunRepository(db)
    all_runs = await repo.get_by_replay_batch_id(replay_batch_id, current_user.user_id)
    if not all_runs:
        raise HTTPException(status_code=404, detail=f"Replay batch {replay_batch_id} not found.")

    completed = [r for r in all_runs if r.status == ResearchRunStatus.COMPLETED.value]
    if not completed:
        raise HTTPException(
            status_code=422,
            detail="No completed runs in this replay batch. Wait for runs to finish and retry.",
        )

    # Derive date window from as_of_date values in metadata
    as_of_dates = [
        _dt.date.fromisoformat(r.metadata_json["as_of_date"])
        for r in completed
        if r.metadata_json.get("as_of_date")
    ]
    start_date = min(as_of_dates)
    end_date = max(as_of_dates)

    ip_dicts: list[dict[str, Any]] | None = None
    if body.initial_positions:
        ip_dicts = [{"symbol": ip.symbol, "quantity": ip.quantity} for ip in body.initial_positions]

    assumptions = {
        "source": "replay_batch_backtest",
        "replay_batch_id": replay_batch_id,
        "completed_run_count": len(completed),
        "total_run_count": len(all_runs),
    }

    try:
        run = await run_advisor_backtest(
            session=db,
            user_id=current_user.user_id,
            start_date=start_date,
            end_date=end_date,
            initial_cash=body.initial_cash,
            benchmark_symbol=body.benchmark_symbol,
            name=body.name or f"Replay batch {replay_batch_id[:8]}",
            assumptions=assumptions,
            recommendation_source="REPLAY_BATCH",
            pinned_run_ids=[r.id for r in completed],
            initial_positions=ip_dicts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await db.commit()

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


@router.get("/historical-replay/{replay_batch_id}/report")
async def get_replay_batch_report(
    replay_batch_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Return a deterministic quality report for a completed historical replay batch.

    Groups recommendations by symbol and tracks how they evolved across replay dates.
    Returns 404 if the batch does not exist or belongs to a different user.
    Returns 422 if the batch has no COMPLETED runs.
    No LLM calls. No external data fetches.
    """
    from backtesting.replay_report import (  # noqa: PLC0415
        build_report_point,
        build_timeline_changes,
        build_timeline_summary,
    )

    repo = ResearchRunRepository(db)
    all_runs = await repo.get_by_replay_batch_id(replay_batch_id, current_user.user_id)
    if not all_runs:
        raise HTTPException(status_code=404, detail=f"Replay batch {replay_batch_id} not found.")

    completed = [r for r in all_runs if r.status == ResearchRunStatus.COMPLETED.value]
    if not completed:
        raise HTTPException(
            status_code=422,
            detail="No completed runs in this replay batch. Cannot build report yet.",
        )

    # Map run_id → as_of_date for point construction
    run_to_date: dict[uuid_mod.UUID, str] = {
        r.id: str(r.metadata_json.get("as_of_date", "")) for r in completed
    }

    # Fetch all neutral recs for these runs in one query
    rec_repo = RecommendationRepository(db)
    neutrals = await rec_repo.get_neutral_recs_by_run_ids([r.id for r in completed])

    # Fetch personalized recs for all neutrals in one query
    neutral_ids = [n.id for n in neutrals]
    personalized_map = await rec_repo.get_latest_personalized_by_neutral_ids(neutral_ids)

    # Group points by symbol, sorted by as_of_date
    symbol_points: dict[str, list[dict[str, Any]]] = {}
    for n in neutrals:
        aod = run_to_date.get(n.research_run_id, "")
        pers = personalized_map.get(n.id)
        point = build_report_point(
            run_id=str(n.research_run_id),
            as_of_date=aod,
            neutral_action=n.action,
            neutral_score=n.score,
            personalized_action=pers.personal_action if pers else None,
            price_at_recommendation=(
                float(n.price_at_recommendation) if n.price_at_recommendation else None
            ),
            score_breakdown=n.score_breakdown_json or {},
            missing_details=n.missing_details_json or [],
            created_at=n.created_at.isoformat() if n.created_at else None,
        )
        symbol_points.setdefault(n.symbol.upper(), []).append(point)

    # Sort each symbol's points by as_of_date ascending
    for pts in symbol_points.values():
        pts.sort(key=lambda p: p["as_of_date"])

    all_as_of = [v for run in completed for v in [run_to_date.get(run.id, "")] if v]

    timelines = [
        {
            "symbol": sym,
            "points": pts,
            "summary": build_timeline_summary(pts),
            "changes": build_timeline_changes(pts),
        }
        for sym, pts in sorted(symbol_points.items())
    ]

    return api_response(
        {
            "replay_batch_id": replay_batch_id,
            "completed_run_count": len(completed),
            "symbols": sorted(symbol_points.keys()),
            "first_as_of_date": min(all_as_of) if all_as_of else None,
            "last_as_of_date": max(all_as_of) if all_as_of else None,
            "timelines": timelines,
        },
        request,
    )


@router.post("/historical-replay/{replay_batch_id}/evaluation", status_code=201)
async def create_replay_batch_evaluation(
    replay_batch_id: str,
    body: ReplayBatchBacktestRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Run a combined evaluation for a completed historical replay batch.

    Combines batch run counts, per-symbol recommendation timeline (from the
    replay report), and a follow-the-advisor backtest (portfolio P&L, trades).

    Returns 404 if batch not found or belongs to another user.
    Returns 422 if no completed runs exist.
    No LLM calls. Deterministic.
    """
    import datetime as _dt  # noqa: PLC0415

    from backtesting.advisor_simulation import run_advisor_backtest  # noqa: PLC0415
    from backtesting.replay_evaluation import build_evaluation  # noqa: PLC0415
    from backtesting.replay_report import (  # noqa: PLC0415
        build_report_point,
        build_timeline_changes,
        build_timeline_summary,
    )
    from sqlalchemy.orm import selectinload  # noqa: PLC0415

    # ── 1. Validate batch ──────────────────────────────────────────────────────
    repo = ResearchRunRepository(db)
    all_runs = await repo.get_by_replay_batch_id(replay_batch_id, current_user.user_id)
    if not all_runs:
        raise HTTPException(status_code=404, detail=f"Replay batch {replay_batch_id} not found.")

    completed = [r for r in all_runs if r.status == ResearchRunStatus.COMPLETED.value]
    if not completed:
        raise HTTPException(
            status_code=422,
            detail="No completed runs in this replay batch. Wait for runs to finish and retry.",
        )

    # ── 2. Run counts ──────────────────────────────────────────────────────────
    counts: dict[str, int] = {}
    for r in all_runs:
        counts[r.status] = counts.get(r.status, 0) + 1
    total = len(all_runs)
    run_counts = {
        "total": total,
        "completed": counts.get("COMPLETED", 0),
        "failed": counts.get("FAILED", 0),
        "queued": counts.get("QUEUED", 0),
        "running": counts.get("RUNNING", 0),
    }

    # ── 3. Build replay report timelines (same logic as get_replay_batch_report) ─
    run_to_date: dict[uuid_mod.UUID, str] = {
        r.id: str(r.metadata_json.get("as_of_date", "")) for r in completed
    }

    rec_repo = RecommendationRepository(db)
    neutrals = await rec_repo.get_neutral_recs_by_run_ids([r.id for r in completed])
    neutral_ids = [n.id for n in neutrals]
    personalized_map = await rec_repo.get_latest_personalized_by_neutral_ids(neutral_ids)

    symbol_points: dict[str, list[dict[str, Any]]] = {}
    for n in neutrals:
        aod = run_to_date.get(n.research_run_id, "")
        pers = personalized_map.get(n.id)
        point = build_report_point(
            run_id=str(n.research_run_id),
            as_of_date=aod,
            neutral_action=n.action,
            neutral_score=n.score,
            personalized_action=pers.personal_action if pers else None,
            price_at_recommendation=(
                float(n.price_at_recommendation) if n.price_at_recommendation else None
            ),
            score_breakdown=n.score_breakdown_json or {},
            missing_details=n.missing_details_json or [],
            created_at=n.created_at.isoformat() if n.created_at else None,
        )
        symbol_points.setdefault(n.symbol.upper(), []).append(point)

    for pts in symbol_points.values():
        pts.sort(key=lambda p: p["as_of_date"])

    timelines = [
        {
            "symbol": sym,
            "points": pts,
            "summary": build_timeline_summary(pts),
            "changes": build_timeline_changes(pts),
        }
        for sym, pts in sorted(symbol_points.items())
    ]
    symbols = sorted(symbol_points.keys())

    # ── 4. Date range from as_of_dates ─────────────────────────────────────────
    all_as_of = [v for v in run_to_date.values() if v]
    start_date_str = min(all_as_of) if all_as_of else ""
    end_date_str = max(all_as_of) if all_as_of else ""

    as_of_dates = [
        _dt.date.fromisoformat(r.metadata_json["as_of_date"])
        for r in completed
        if r.metadata_json.get("as_of_date")
    ]
    start_date = min(as_of_dates)
    end_date = max(as_of_dates)

    # ── 5. Run advisor backtest with pinned completed run IDs ──────────────────
    ip_dicts: list[dict[str, Any]] | None = None
    if body.initial_positions:
        ip_dicts = [{"symbol": ip.symbol, "quantity": ip.quantity} for ip in body.initial_positions]

    assumptions = {
        "source": "replay_batch_evaluation",
        "replay_batch_id": replay_batch_id,
        "completed_run_count": len(completed),
        "total_run_count": total,
    }

    try:
        backtest_run = await run_advisor_backtest(
            session=db,
            user_id=current_user.user_id,
            start_date=start_date,
            end_date=end_date,
            initial_cash=body.initial_cash,
            benchmark_symbol=body.benchmark_symbol,
            name=body.name or f"Evaluation {replay_batch_id[:8]}",
            assumptions=assumptions,
            recommendation_source="REPLAY_BATCH",
            pinned_run_ids=[r.id for r in completed],
            initial_positions=ip_dicts,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    await db.commit()

    # Reload with trades eagerly (run_advisor_backtest already does this, but be explicit)
    from db.models import AdvisorBacktestRun  # noqa: PLC0415
    from sqlalchemy import select as _select  # noqa: PLC0415

    result = await db.execute(
        _select(AdvisorBacktestRun)
        .options(selectinload(AdvisorBacktestRun.trades))
        .where(AdvisorBacktestRun.id == backtest_run.id)
    )
    backtest_run = result.scalar_one()

    # ── 6. Convert ORM objects to plain dicts for pure helper ──────────────────
    backtest_run_fields: dict[str, Any] = {
        "initial_cash": float(backtest_run.initial_cash),
        "final_equity": float(backtest_run.final_equity)
        if backtest_run.final_equity is not None
        else None,
        "total_return_pct": float(backtest_run.total_return_pct)
        if backtest_run.total_return_pct is not None
        else None,
        "benchmark_symbol": backtest_run.benchmark_symbol,
        "benchmark_return_pct": float(backtest_run.benchmark_return_pct)
        if backtest_run.benchmark_return_pct is not None
        else None,
        "relative_return_pct": float(backtest_run.relative_return_pct)
        if backtest_run.relative_return_pct is not None
        else None,
        "max_drawdown_pct": float(backtest_run.max_drawdown_pct)
        if backtest_run.max_drawdown_pct is not None
        else None,
        "total_trades": backtest_run.total_trades,
        "winning_trades": backtest_run.winning_trades,
        "losing_trades": backtest_run.losing_trades,
    }

    backtest_trades_dicts: list[dict[str, Any]] = [
        {
            "symbol": t.symbol,
            "action": t.action,
            "trade_type": t.trade_type,
            "reason": t.reason,
            "quantity": float(t.quantity) if t.quantity is not None else None,
            "price": float(t.price) if t.price is not None else None,
            "cash_delta": float(t.cash_delta) if t.cash_delta is not None else None,
            "raw_json": dict(t.raw_json or {}),
        }
        for t in backtest_run.trades
    ]

    # ── 7. Build combined evaluation ───────────────────────────────────────────
    evaluation = build_evaluation(
        replay_batch_id=replay_batch_id,
        date_range={"start_date": start_date_str, "end_date": end_date_str},
        symbols=symbols,
        run_counts=run_counts,
        timelines=timelines,
        backtest_run_id=str(backtest_run.id),
        backtest_run_fields=backtest_run_fields,
        backtest_summary_json=dict(backtest_run.summary_json or {}),
        backtest_trades=backtest_trades_dicts,
    )

    return api_response(evaluation, request)
