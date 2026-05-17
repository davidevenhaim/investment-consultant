"""Research worker tasks — Celery tasks for async research execution.

Architecture
------------
All business logic lives in the private ``_execute_*_async`` helpers so they
can be tested directly with pytest-asyncio without needing a real Celery worker.
The public ``@shared_task`` functions are thin wrappers that call
``_run_async()`` to bridge the sync Celery boundary.

Event-loop strategy
-------------------
``asyncio.run()`` creates a **new** event loop and then **closes it** after
every call.  SQLAlchemy's async engine (backed by asyncpg) caches ``Future``
objects bound to the loop that was active when the engine was first
initialised.  If that loop is destroyed and a new one is created for the next
task, every pool access raises:

    RuntimeError: Task <…> got Future <…> attached to a different loop

Fix: maintain one persistent event loop per worker *process*  (``_worker_loop``).
Tasks call ``_run_async()`` which uses ``loop.run_until_complete()`` instead of
``asyncio.run()``.  The loop — and the asyncpg pool Futures bound to it — are
never destroyed between task invocations.

Session isolation
-----------------
Each task creates its own ``AsyncSession`` via ``get_session_factory()``.
This is intentional: the API request session must never be shared with a
Celery worker process.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from celery import shared_task
from core.config import get_settings
from core.logging import get_logger
from db.session import get_session_factory
from research_graph.runner import run_research_for_run

logger = get_logger(__name__)

# ── Per-worker persistent event loop ──────────────────────────────────────────
# One loop per worker process; never closed between tasks.  See module docstring.

_worker_loop: asyncio.AbstractEventLoop | None = None


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return the persistent per-process event loop, creating it if needed."""
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def _run_async(coro: Any) -> Any:
    """Run *coro* on the per-worker event loop.

    Never use asyncio.run() in Celery tasks — it closes the loop after every
    call, invalidating asyncpg pool Futures.  This helper uses
    loop.run_until_complete() so the loop stays alive across task invocations.
    """
    return _get_worker_loop().run_until_complete(coro)


# ── Task name constants ─────────────────────────────────────────────────────────
# Use these in API routes instead of importing the task object and calling .delay().
# Dispatching via celery_app.send_task(NAME, args=[...]) ensures the configured
# broker URL is used regardless of which Celery app is "current" in that process.

RUN_RESEARCH_RUN_TASK_NAME = "apps.worker.tasks.research.run_research_run_task"
SCHEDULED_RESEARCH_TASK_NAME = "apps.worker.tasks.research.scheduled_research_task"
RUN_SCHEDULED_RESEARCH_TASK_NAME = "apps.worker.tasks.research.run_scheduled_research"


# ── Core async helpers ─────────────────────────────────────────────────────────


async def _execute_research_run_async(
    research_run_id: str,
    user_id: str | None = None,
    broker_account_id: str | None = None,
) -> dict[str, Any]:
    """Execute a research run inside a fresh DB session.

    This is the testable core of ``run_research_run_task``. Call it directly
    in tests via ``await _execute_research_run_async(...)``.
    """
    from db.enums import ResearchRunStatus
    from db.repositories import (
        BrokerAccountRepository,
        ResearchRunRepository,
        StrategyVersionRepository,
    )

    run_uuid = uuid.UUID(research_run_id)
    factory = get_session_factory()

    async with factory() as session:
        run_repo = ResearchRunRepository(session)

        run = await run_repo.get_by_id_internal(run_uuid)
        if run is None:
            logger.error("research_run_task_not_found", run_id=research_run_id)
            return {"status": "not_found", "run_id": research_run_id}

        await run_repo.update_status(run_uuid, ResearchRunStatus.RUNNING)
        await session.commit()

        # Detect historical replay runs and extract as_of_date
        metadata = run.metadata_json or {}
        is_replay = bool(metadata.get("historical_replay"))
        as_of_date_str: str | None = metadata.get("as_of_date") if is_replay else None

        logger.info(
            "research_run_task_started",
            run_id=research_run_id,
            symbol_count=len(run.tickers),
            is_replay=is_replay,
            as_of_date=as_of_date_str,
        )

        # Resolve broker account
        resolved_broker_id: uuid.UUID | None = None
        if broker_account_id:
            resolved_broker_id = uuid.UUID(broker_account_id)
        elif run.user_id is not None:
            try:
                ba_repo = BrokerAccountRepository(session)
                ba = await ba_repo.get_active_default(user_id=run.user_id)
                resolved_broker_id = ba.id if ba else None
            except Exception as exc:
                logger.warning(
                    "research_run_task_broker_resolve_failed",
                    run_id=research_run_id,
                    error=str(exc),
                )

        sv_repo = StrategyVersionRepository(session)
        active_sv = await sv_repo.get_active()
        strategy_version = active_sv.version if active_sv else "v0.1.0"

        tickers = run.tickers

        try:
            summary = await run_research_for_run(
                run,
                tickers,
                session,
                strategy_version,
                broker_account_id=resolved_broker_id,
                enforce_broker_scope=True,
                as_of_date=as_of_date_str,
            )
            if summary["symbols_failed"]:
                final_status = ResearchRunStatus.FAILED
                error_message: str | None = (
                    f"Failed symbols: {', '.join(summary['symbols_failed'])}"
                )
            else:
                final_status = ResearchRunStatus.COMPLETED
                error_message = None
        except Exception as exc:
            logger.error(
                "research_run_task_graph_error",
                run_id=research_run_id,
                error=str(exc),
            )
            summary = {"symbols_completed": [], "symbols_failed": [], "errors": [str(exc)]}
            final_status = ResearchRunStatus.FAILED
            error_message = str(exc)[:500]

        # For historical replay, back-date finished_at to as_of_date 16:00 UTC so
        # advisor backtest date queries (ResearchRun.finished_at >= start_date) find
        # the run in the correct historical window.
        replay_finished_at: datetime | None = None
        if is_replay and as_of_date_str:
            try:
                from datetime import date as _date  # noqa: PLC0415

                d = _date.fromisoformat(as_of_date_str)
                replay_finished_at = datetime(d.year, d.month, d.day, 16, 0, 0, tzinfo=UTC)
            except ValueError:
                logger.warning(
                    "research_run_task_invalid_as_of_date",
                    run_id=research_run_id,
                    as_of_date=as_of_date_str,
                )

        await run_repo.update_status(
            run_uuid,
            final_status,
            error_message=error_message,
            finished_at=replay_finished_at,
        )
        await session.commit()

        logger.info(
            "research_run_task_completed",
            run_id=research_run_id,
            status=final_status.value,
            completed=summary.get("symbols_completed", []),
            failed=summary.get("symbols_failed", []),
        )
        return {
            "status": final_status.value,
            "run_id": research_run_id,
            "summary": summary,
        }


async def _execute_scheduled_research_async() -> dict[str, Any]:
    """Create and enqueue a scheduled research run for the configured user.

    This is the testable core of ``scheduled_research_task``. Call it directly
    in tests via ``await _execute_scheduled_research_async()``.
    """
    settings = get_settings()

    if not settings.scheduled_research_enabled:
        logger.info("scheduled_research_disabled")
        return {"status": "disabled"}

    user_id = uuid.UUID(settings.scheduled_research_user_id)
    user_id_str = str(user_id)

    from db.enums import ResearchRunStatus, ResearchRunType
    from db.repositories import (
        BrokerAccountRepository,
        ResearchRunRepository,
        StrategyVersionRepository,
        WatchlistRepository,
    )

    factory = get_session_factory()

    async with factory() as session:
        run_repo = ResearchRunRepository(session)

        # Deduplicate: skip if a QUEUED/RUNNING scheduled run exists in last 6 h
        if await run_repo.has_recent_scheduled_run(user_id, hours=6):
            logger.info(
                "scheduled_research_skipped_duplicate",
                user_id=user_id_str,
            )
            return {"status": "skipped", "reason": "recent_scheduled_run_exists"}

        wl_repo = WatchlistRepository(session)
        active = await wl_repo.list_active(user_id=user_id)
        symbols = [w.symbol for w in active]

        if not symbols:
            logger.info(
                "scheduled_research_skipped_empty_watchlist",
                user_id=user_id_str,
            )
            return {"status": "skipped", "reason": "empty_watchlist"}

        sv_repo = StrategyVersionRepository(session)
        active_sv = await sv_repo.get_active()
        sv_id = active_sv.id if active_sv else None

        run = await run_repo.create(
            run_type=ResearchRunType.SCHEDULED,
            strategy_version_id=sv_id,
            user_id=user_id,
        )
        await run_repo.update_status(run.id, ResearchRunStatus.QUEUED)
        await run_repo.add_tickers(run.id, symbols)
        await session.commit()

        run_id_str = str(run.id)
        logger.info(
            "scheduled_research_run_created",
            run_id=run_id_str,
            user_id=user_id_str,
            symbols=symbols,
        )

        # Resolve broker account for the enqueued task
        ba_repo = BrokerAccountRepository(session)
        ba = await ba_repo.get_active_default(user_id=user_id)
        broker_account_id_str = str(ba.id) if ba else None

    # Enqueue outside the session (session is closed after `async with` exits).
    # Use celery_app.send_task() to guarantee we dispatch through the correctly
    # configured broker, regardless of which Celery app is "current" in the process.
    from apps.worker.celery_app import celery_app as _celery_app  # noqa: PLC0415

    _celery_app.send_task(
        RUN_RESEARCH_RUN_TASK_NAME,
        args=[run_id_str, user_id_str, broker_account_id_str],
    )

    return {
        "status": "queued",
        "run_id": run_id_str,
        "symbols": symbols,
    }


# ── Celery task definitions ────────────────────────────────────────────────────


@shared_task(  # type: ignore[untyped-decorator]
    name="apps.worker.tasks.research.run_research_run_task",
    bind=True,
    max_retries=0,
    acks_late=True,
)
def run_research_run_task(
    self: object,
    research_run_id: str,
    user_id: str | None = None,
    broker_account_id: str | None = None,
) -> dict[str, Any]:
    """Celery task: execute a research run given its UUID string.

    Accepts optional ``user_id`` and ``broker_account_id`` as strings so they
    can be serialised to JSON by Celery. When broker is omitted the task
    resolves the user's active default account from the DB.
    """
    logger.info("research_run_task_received", run_id=research_run_id)
    return _run_async(  # type: ignore[no-any-return]
        _execute_research_run_async(research_run_id, user_id, broker_account_id)
    )


@shared_task(  # type: ignore[untyped-decorator]
    name="apps.worker.tasks.research.scheduled_research_task",
    bind=True,
    max_retries=0,
    acks_late=True,
)
def scheduled_research_task(self: object) -> dict[str, Any]:
    """Celery beat task: create and enqueue twice-daily scheduled research runs.

    Controlled by ``SCHEDULED_RESEARCH_ENABLED`` (default: false).
    Skips automatically if a QUEUED/RUNNING scheduled run already exists for
    the configured user within the last 6 hours.
    """
    logger.info("scheduled_research_task_triggered")
    return _run_async(_execute_scheduled_research_async())  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Legacy stub kept for backward-compatibility with any existing beat config.
# Will be removed in M12.1.
# ---------------------------------------------------------------------------


@shared_task(  # type: ignore[untyped-decorator]
    name="apps.worker.tasks.research.run_scheduled_research",
    bind=True,
    max_retries=0,
    acks_late=True,
)
def run_scheduled_research(self: object, run_type: str = "manual") -> dict[str, str]:
    logger.info("run_scheduled_research_legacy_stub", run_type=run_type)
    return {"status": "queued", "run_type": run_type}
