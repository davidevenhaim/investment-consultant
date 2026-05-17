"""Tests for historical replay worker behavior (M12.1).

Tests that:
1. Worker extracts as_of_date from replay metadata and passes it to run_research_for_run.
2. Worker back-dates ResearchRun.finished_at to as_of_date 16:00 UTC for replay runs.
3. Normal (non-replay) async runs pass as_of_date=None and use wall-clock finished_at.
4. Persist node sets NeutralRecommendation.created_at to as_of_date 16:00 UTC.
"""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from apps.api.dependencies.auth import DEV_DEFAULT_USER_ID

# ── Helpers ────────────────────────────────────────────────────────────────────


async def _seed_replay_run(db_session, *, as_of_date: str, symbols=None):
    from db.models import ResearchRun, ResearchRunTicker

    run_id = uuid.uuid4()
    run = ResearchRun(
        id=run_id,
        user_id=DEV_DEFAULT_USER_ID,
        run_type="HISTORICAL_REPLAY",
        status="QUEUED",
        metadata_json={
            "historical_replay": True,
            "replay_batch_id": str(uuid.uuid4()),
            "as_of_date": as_of_date,
            "source": "historical_graph_replay",
            "cadence": "weekly",
        },
    )
    db_session.add(run)
    await db_session.flush()

    for sym in symbols or ["AAPL"]:
        db_session.add(
            ResearchRunTicker(
                research_run_id=run_id,
                symbol=sym,
                status="CREATED",
            )
        )
    await db_session.flush()
    return run


async def _seed_normal_run(db_session, *, symbols=None):
    from db.models import ResearchRun, ResearchRunTicker

    run_id = uuid.uuid4()
    run = ResearchRun(
        id=run_id,
        user_id=DEV_DEFAULT_USER_ID,
        run_type="MANUAL",
        status="QUEUED",
        metadata_json={},
    )
    db_session.add(run)
    await db_session.flush()

    for sym in symbols or ["AAPL"]:
        db_session.add(
            ResearchRunTicker(
                research_run_id=run_id,
                symbol=sym,
                status="CREATED",
            )
        )
    await db_session.flush()
    return run


def _make_session_ctx(session):
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _ctx():
        yield session

    class _Factory:
        def __call__(self):
            return _ctx()

    return _Factory()


# ── Worker as_of_date propagation ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_worker_passes_as_of_date_for_replay_run(db_session):
    """Worker passes as_of_date from metadata to run_research_for_run."""
    from apps.worker.tasks.research import _execute_research_run_async

    run = await _seed_replay_run(db_session, as_of_date="2026-01-15")

    mock_summary = {"symbols_completed": ["AAPL"], "symbols_failed": [], "errors": []}

    with (
        patch("apps.worker.tasks.research.get_session_factory") as mock_factory,
        patch(
            "apps.worker.tasks.research.run_research_for_run", new_callable=AsyncMock
        ) as mock_graph,
    ):
        mock_factory.return_value = _make_session_ctx(db_session)
        mock_graph.return_value = mock_summary

        await _execute_research_run_async(str(run.id))

    # Verify as_of_date was passed through
    call_kwargs = mock_graph.call_args
    assert call_kwargs is not None
    assert call_kwargs.kwargs.get("as_of_date") == "2026-01-15"


@pytest.mark.asyncio
async def test_worker_passes_none_as_of_date_for_normal_run(db_session):
    """Normal (non-replay) async runs pass as_of_date=None."""
    from apps.worker.tasks.research import _execute_research_run_async

    run = await _seed_normal_run(db_session)

    mock_summary = {"symbols_completed": ["AAPL"], "symbols_failed": [], "errors": []}

    with (
        patch("apps.worker.tasks.research.get_session_factory") as mock_factory,
        patch(
            "apps.worker.tasks.research.run_research_for_run", new_callable=AsyncMock
        ) as mock_graph,
    ):
        mock_factory.return_value = _make_session_ctx(db_session)
        mock_graph.return_value = mock_summary

        await _execute_research_run_async(str(run.id))

    call_kwargs = mock_graph.call_args
    assert call_kwargs.kwargs.get("as_of_date") is None


@pytest.mark.asyncio
async def test_worker_back_dates_finished_at_for_replay_run(db_session):
    """Replay run's finished_at is set to as_of_date 16:00 UTC on completion."""
    from db.enums import ResearchRunStatus

    from apps.worker.tasks.research import _execute_research_run_async

    run = await _seed_replay_run(db_session, as_of_date="2026-01-15")

    mock_summary = {"symbols_completed": ["AAPL"], "symbols_failed": [], "errors": []}

    with (
        patch("apps.worker.tasks.research.get_session_factory") as mock_factory,
        patch(
            "apps.worker.tasks.research.run_research_for_run", new_callable=AsyncMock
        ) as mock_graph,
    ):
        mock_factory.return_value = _make_session_ctx(db_session)
        mock_graph.return_value = mock_summary

        await _execute_research_run_async(str(run.id))

    await db_session.refresh(run)
    assert run.status == ResearchRunStatus.COMPLETED.value
    expected_finished_at = datetime(2026, 1, 15, 16, 0, 0, tzinfo=UTC)
    assert run.finished_at == expected_finished_at


@pytest.mark.asyncio
async def test_worker_normal_run_uses_wall_clock_finished_at(db_session):
    """Normal run's finished_at is close to the actual wall-clock time."""
    from db.enums import ResearchRunStatus

    from apps.worker.tasks.research import _execute_research_run_async

    before = datetime.now(UTC)
    run = await _seed_normal_run(db_session)

    mock_summary = {"symbols_completed": ["AAPL"], "symbols_failed": [], "errors": []}

    with (
        patch("apps.worker.tasks.research.get_session_factory") as mock_factory,
        patch(
            "apps.worker.tasks.research.run_research_for_run", new_callable=AsyncMock
        ) as mock_graph,
    ):
        mock_factory.return_value = _make_session_ctx(db_session)
        mock_graph.return_value = mock_summary

        await _execute_research_run_async(str(run.id))

    after = datetime.now(UTC)

    await db_session.refresh(run)
    assert run.status == ResearchRunStatus.COMPLETED.value
    # finished_at should be between before and after (wall-clock, not 2026-01-15)
    assert before <= run.finished_at <= after


@pytest.mark.asyncio
async def test_worker_failed_replay_run_is_marked_failed(db_session):
    """Replay run is still marked FAILED if graph raises."""
    from db.enums import ResearchRunStatus

    from apps.worker.tasks.research import _execute_research_run_async

    run = await _seed_replay_run(db_session, as_of_date="2026-01-15")

    with (
        patch("apps.worker.tasks.research.get_session_factory") as mock_factory,
        patch(
            "apps.worker.tasks.research.run_research_for_run", new_callable=AsyncMock
        ) as mock_graph,
    ):
        mock_factory.return_value = _make_session_ctx(db_session)
        mock_graph.side_effect = RuntimeError("graph exploded")

        result = await _execute_research_run_async(str(run.id))

    assert result["status"] == "FAILED"
    await db_session.refresh(run)
    assert run.status == ResearchRunStatus.FAILED.value


# ── make_initial_state as_of_date ─────────────────────────────────────────────


def test_make_initial_state_includes_as_of_date():
    """make_initial_state stores as_of_date in state when provided."""
    from datetime import date
    from types import SimpleNamespace

    from research_graph.runner import make_initial_state

    run = SimpleNamespace(id=uuid.uuid4(), user_id=DEV_DEFAULT_USER_ID)
    ticker = SimpleNamespace(id=uuid.uuid4(), symbol="AAPL")

    state = make_initial_state(run, ticker, "v0.1.0", as_of_date=date(2026, 1, 15))  # type: ignore[arg-type]
    assert state["as_of_date"] == "2026-01-15"


def test_make_initial_state_as_of_date_none_by_default():
    """make_initial_state has as_of_date=None when not provided."""
    from types import SimpleNamespace

    from research_graph.runner import make_initial_state

    run = SimpleNamespace(id=uuid.uuid4(), user_id=None)
    ticker = SimpleNamespace(id=uuid.uuid4(), symbol="NVDA")

    state = make_initial_state(run, ticker, "v0.1.0")  # type: ignore[arg-type]
    assert state["as_of_date"] is None
