"""Tests for async research worker tasks.

Architecture note
-----------------
We test ``_execute_research_run_async`` and ``_execute_scheduled_research_async``
directly (the async helpers) rather than the Celery task wrappers.
This avoids needing a live Redis/broker while exercising all the business logic.

The Celery tasks themselves are thin ``asyncio.run()`` wrappers that are
verified by checking they are importable and have the correct task name.
"""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from apps.api.dependencies.auth import DEV_DEFAULT_USER_ID

# ── Helpers ────────────────────────────────────────────────────────────────────


async def _seed_research_run(db_session, *, symbols=None, run_type="MANUAL", status="QUEUED"):
    """Create a minimal ResearchRun + tickers for testing."""
    import uuid as uuid_mod

    from db.models import ResearchRun, ResearchRunTicker

    run_id = uuid_mod.uuid4()
    run = ResearchRun(
        id=run_id,
        user_id=DEV_DEFAULT_USER_ID,
        run_type=run_type,
        status=status,
    )
    db_session.add(run)
    await db_session.flush()

    tickers = []
    for sym in symbols or ["AAPL"]:
        t = ResearchRunTicker(
            research_run_id=run_id,
            symbol=sym,
            status="CREATED",
        )
        db_session.add(t)
        tickers.append(t)
    await db_session.flush()

    return run, tickers


# ── Task import / name sanity ──────────────────────────────────────────────────


def test_celery_task_names_are_correct():
    """Task names must match the string used in beat_schedule and .delay() calls."""
    from apps.worker.tasks.research import run_research_run_task, scheduled_research_task

    assert run_research_run_task.name == "apps.worker.tasks.research.run_research_run_task"
    assert scheduled_research_task.name == "apps.worker.tasks.research.scheduled_research_task"


# ── _execute_research_run_async ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_research_run_not_found(db_session):
    """Returns not_found gracefully when run_id does not exist."""
    from apps.worker.tasks.research import _execute_research_run_async

    fake_id = str(uuid.uuid4())
    with patch("apps.worker.tasks.research.get_session_factory") as mock_factory:
        mock_factory.return_value = _make_session_ctx(db_session)
        result = await _execute_research_run_async(fake_id)

    assert result["status"] == "not_found"
    assert result["run_id"] == fake_id


@pytest.mark.asyncio
async def test_execute_research_run_marks_running_then_completed(db_session):
    """Task transitions QUEUED → RUNNING → COMPLETED on graph success."""
    from db.enums import ResearchRunStatus

    from apps.worker.tasks.research import _execute_research_run_async

    run, _ = await _seed_research_run(db_session, symbols=["AAPL"], status="QUEUED")
    run_id = str(run.id)

    _mock_summary = {
        "symbols_completed": ["AAPL"],
        "symbols_failed": [],
        "errors": [],
    }

    with (
        patch("apps.worker.tasks.research.get_session_factory") as mock_factory,
        patch(
            "apps.worker.tasks.research.run_research_for_run", new_callable=AsyncMock
        ) as mock_graph,
    ):
        mock_factory.return_value = _make_session_ctx(db_session)
        mock_graph.return_value = _mock_summary

        result = await _execute_research_run_async(run_id)

    assert result["status"] == "COMPLETED"
    assert result["run_id"] == run_id

    await db_session.refresh(run)
    assert run.status == ResearchRunStatus.COMPLETED.value
    assert run.started_at is not None
    assert run.finished_at is not None


@pytest.mark.asyncio
async def test_execute_research_run_marks_failed_on_graph_exception(db_session):
    """Task transitions QUEUED → RUNNING → FAILED when graph raises."""
    from db.enums import ResearchRunStatus

    from apps.worker.tasks.research import _execute_research_run_async

    run, _ = await _seed_research_run(db_session, symbols=["AAPL"], status="QUEUED")
    run_id = str(run.id)

    with (
        patch("apps.worker.tasks.research.get_session_factory") as mock_factory,
        patch(
            "apps.worker.tasks.research.run_research_for_run", new_callable=AsyncMock
        ) as mock_graph,
    ):
        mock_factory.return_value = _make_session_ctx(db_session)
        mock_graph.side_effect = RuntimeError("graph exploded")

        result = await _execute_research_run_async(run_id)

    assert result["status"] == "FAILED"
    await db_session.refresh(run)
    assert run.status == ResearchRunStatus.FAILED.value
    assert run.error_message is not None


@pytest.mark.asyncio
async def test_execute_research_run_marks_failed_when_symbols_failed(db_session):
    """Task returns FAILED when graph summary has symbols_failed (partial failure)."""
    from db.enums import ResearchRunStatus

    from apps.worker.tasks.research import _execute_research_run_async

    run, _ = await _seed_research_run(db_session, symbols=["AAPL", "NVDA"], status="QUEUED")
    run_id = str(run.id)

    _mock_summary = {
        "symbols_completed": ["AAPL"],
        "symbols_failed": ["NVDA"],
        "errors": ["NVDA: something"],
    }

    with (
        patch("apps.worker.tasks.research.get_session_factory") as mock_factory,
        patch(
            "apps.worker.tasks.research.run_research_for_run", new_callable=AsyncMock
        ) as mock_graph,
    ):
        mock_factory.return_value = _make_session_ctx(db_session)
        mock_graph.return_value = _mock_summary

        result = await _execute_research_run_async(run_id)

    assert result["status"] == "FAILED"
    await db_session.refresh(run)
    assert run.status == ResearchRunStatus.FAILED.value


# ── _execute_scheduled_research_async ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_scheduled_task_returns_disabled_when_not_enabled(monkeypatch):
    """Scheduled task no-ops when SCHEDULED_RESEARCH_ENABLED=false."""
    monkeypatch.setenv("SCHEDULED_RESEARCH_ENABLED", "false")
    from core.config import get_settings

    get_settings.cache_clear()

    from apps.worker.tasks.research import _execute_scheduled_research_async

    result = await _execute_scheduled_research_async()
    assert result["status"] == "disabled"

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_scheduled_task_skips_empty_watchlist(db_session, monkeypatch):
    """Scheduled task no-ops gracefully when watchlist is empty."""
    monkeypatch.setenv("SCHEDULED_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("SCHEDULED_RESEARCH_USER_ID", str(DEV_DEFAULT_USER_ID))
    from core.config import get_settings

    get_settings.cache_clear()

    from apps.worker.tasks.research import _execute_scheduled_research_async

    with patch("apps.worker.tasks.research.get_session_factory") as mock_factory:
        mock_factory.return_value = _make_session_ctx(db_session)
        result = await _execute_scheduled_research_async()

    assert result["status"] == "skipped"
    assert result["reason"] == "empty_watchlist"

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_scheduled_task_creates_queued_run_when_watchlist_nonempty(db_session, monkeypatch):
    """Scheduled task creates a QUEUED SCHEDULED run when watchlist has symbols."""
    monkeypatch.setenv("SCHEDULED_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("SCHEDULED_RESEARCH_USER_ID", str(DEV_DEFAULT_USER_ID))
    from core.config import get_settings

    get_settings.cache_clear()

    # Seed a watchlist symbol
    from db.models import WatchlistSymbol

    wl = WatchlistSymbol(
        user_id=DEV_DEFAULT_USER_ID,
        symbol="AAPL",
        asset_type="EQUITY",
        is_active=True,
    )
    db_session.add(wl)
    await db_session.flush()

    from apps.worker.tasks.research import _execute_scheduled_research_async

    with (
        patch("apps.worker.tasks.research.get_session_factory") as mock_factory,
        patch("apps.worker.celery_app.celery_app") as mock_celery,
    ):
        mock_factory.return_value = _make_session_ctx(db_session)
        mock_celery.send_task = MagicMock()

        result = await _execute_scheduled_research_async()

    assert result["status"] == "queued"
    assert "AAPL" in result["symbols"]
    assert "run_id" in result
    mock_celery.send_task.assert_called_once()

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_scheduled_task_does_not_duplicate_recent_queued_run(db_session, monkeypatch):
    """Scheduled task skips if a QUEUED SCHEDULED run was created recently."""
    monkeypatch.setenv("SCHEDULED_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("SCHEDULED_RESEARCH_USER_ID", str(DEV_DEFAULT_USER_ID))
    from core.config import get_settings

    get_settings.cache_clear()

    # Seed a recent QUEUED SCHEDULED run
    from db.models import ResearchRun

    recent_run = ResearchRun(
        id=uuid.uuid4(),
        user_id=DEV_DEFAULT_USER_ID,
        run_type="SCHEDULED",
        status="QUEUED",
        created_at=datetime.now(UTC) - timedelta(hours=2),
    )
    db_session.add(recent_run)
    await db_session.flush()

    from apps.worker.tasks.research import _execute_scheduled_research_async

    with patch("apps.worker.tasks.research.get_session_factory") as mock_factory:
        mock_factory.return_value = _make_session_ctx(db_session)
        result = await _execute_scheduled_research_async()

    assert result["status"] == "skipped"
    assert result["reason"] == "recent_scheduled_run_exists"

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_scheduled_task_uses_user_scoped_watchlist(db_session, monkeypatch):
    """Scheduled task only reads watchlist symbols for the configured user."""
    monkeypatch.setenv("SCHEDULED_RESEARCH_ENABLED", "true")
    monkeypatch.setenv("SCHEDULED_RESEARCH_USER_ID", str(DEV_DEFAULT_USER_ID))
    from core.config import get_settings

    get_settings.cache_clear()

    other_user = uuid.uuid4()

    # Seed symbols: one for other_user (should not be picked up), one for DEV_DEFAULT
    from db.models import WatchlistSymbol

    db_session.add(
        WatchlistSymbol(
            user_id=DEV_DEFAULT_USER_ID, symbol="MSFT", asset_type="EQUITY", is_active=True
        )
    )
    db_session.add(
        WatchlistSymbol(user_id=other_user, symbol="AMZN", asset_type="EQUITY", is_active=True)
    )
    await db_session.flush()

    from apps.worker.tasks.research import _execute_scheduled_research_async

    with (
        patch("apps.worker.tasks.research.get_session_factory") as mock_factory,
        patch("apps.worker.celery_app.celery_app") as mock_celery,
    ):
        mock_factory.return_value = _make_session_ctx(db_session)
        mock_celery.send_task = MagicMock()

        result = await _execute_scheduled_research_async()

    assert result["status"] == "queued"
    assert result["symbols"] == ["MSFT"]
    assert "AMZN" not in result["symbols"]

    get_settings.cache_clear()


# ── Repository helpers ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_by_id_internal_no_user_filter(db_session):
    """get_by_id_internal returns the run regardless of user ownership."""
    from db.repositories import ResearchRunRepository

    run, _ = await _seed_research_run(db_session, symbols=["AAPL"])
    repo = ResearchRunRepository(db_session)

    result = await repo.get_by_id_internal(run.id)
    assert result is not None
    assert result.id == run.id


@pytest.mark.asyncio
async def test_has_recent_scheduled_run_true(db_session):
    """has_recent_scheduled_run returns True when QUEUED SCHEDULED run exists."""
    from db.models import ResearchRun
    from db.repositories import ResearchRunRepository

    run = ResearchRun(
        id=uuid.uuid4(),
        user_id=DEV_DEFAULT_USER_ID,
        run_type="SCHEDULED",
        status="QUEUED",
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(run)
    await db_session.flush()

    repo = ResearchRunRepository(db_session)
    assert await repo.has_recent_scheduled_run(DEV_DEFAULT_USER_ID, hours=6) is True


@pytest.mark.asyncio
async def test_has_recent_scheduled_run_false_when_old(db_session):
    """has_recent_scheduled_run returns False when only old SCHEDULED runs exist."""
    from db.models import ResearchRun
    from db.repositories import ResearchRunRepository

    old_run = ResearchRun(
        id=uuid.uuid4(),
        user_id=DEV_DEFAULT_USER_ID,
        run_type="SCHEDULED",
        status="QUEUED",
        created_at=datetime.now(UTC) - timedelta(hours=10),
    )
    db_session.add(old_run)
    await db_session.flush()

    repo = ResearchRunRepository(db_session)
    assert await repo.has_recent_scheduled_run(DEV_DEFAULT_USER_ID, hours=6) is False


@pytest.mark.asyncio
async def test_has_recent_scheduled_run_false_for_completed(db_session):
    """has_recent_scheduled_run ignores COMPLETED runs; only QUEUED/RUNNING count."""
    from db.models import ResearchRun
    from db.repositories import ResearchRunRepository

    completed_run = ResearchRun(
        id=uuid.uuid4(),
        user_id=DEV_DEFAULT_USER_ID,
        run_type="SCHEDULED",
        status="COMPLETED",
        created_at=datetime.now(UTC) - timedelta(hours=1),
    )
    db_session.add(completed_run)
    await db_session.flush()

    repo = ResearchRunRepository(db_session)
    assert await repo.has_recent_scheduled_run(DEV_DEFAULT_USER_ID, hours=6) is False


# ── Utilities ──────────────────────────────────────────────────────────────────


def _make_session_ctx(session):
    """Return a context-manager factory that always yields the given session.

    Used to patch ``get_session_factory()`` so worker tasks use the test DB
    session (with rollback) instead of creating their own connection.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx():
        yield session

    class _Factory:
        def __call__(self):
            return _ctx()

    return _Factory()
