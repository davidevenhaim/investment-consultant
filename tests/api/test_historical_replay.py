"""Tests for POST /api/v1/research-runs/historical-replay (M12.1)."""

import uuid
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from apps.api.dependencies.auth import DEV_DEFAULT_USER_ID

# ── API endpoint tests ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replay_weekly_creates_correct_run_count(api_client) -> None:
    """Weekly cadence Jan 1–Jan 29 (4 weeks + 1 = 5 dates) creates 5 QUEUED runs."""
    with patch("apps.api.routers.research_runs._celery_app") as mock_celery:
        mock_celery.send_task = MagicMock()
        resp = await api_client.post(
            "/api/v1/research-runs/historical-replay",
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-01-29",
                "symbols": ["AAPL", "NVDA"],
                "cadence": "weekly",
                "async_execution": True,
            },
        )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["count"] == 5  # Jan 1, 8, 15, 22, 29
    assert len(data["runs"]) == 5
    assert mock_celery.send_task.call_count == 5


@pytest.mark.asyncio
async def test_replay_daily_creates_correct_run_count(api_client) -> None:
    """Daily cadence Jan 1–Jan 3 creates 3 runs."""
    with patch("apps.api.routers.research_runs._celery_app") as mock_celery:
        mock_celery.send_task = MagicMock()
        resp = await api_client.post(
            "/api/v1/research-runs/historical-replay",
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-01-03",
                "symbols": ["AAPL"],
                "cadence": "daily",
            },
        )

    assert resp.status_code == 201
    assert resp.json()["data"]["count"] == 3
    assert mock_celery.send_task.call_count == 3


@pytest.mark.asyncio
async def test_replay_monthly_creates_correct_run_count(api_client) -> None:
    """Monthly cadence Jan 1–Mar 1 creates 3 runs (Jan, Feb, Mar)."""
    with patch("apps.api.routers.research_runs._celery_app") as mock_celery:
        mock_celery.send_task = MagicMock()
        resp = await api_client.post(
            "/api/v1/research-runs/historical-replay",
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-03-01",
                "symbols": ["AAPL"],
                "cadence": "monthly",
            },
        )

    assert resp.status_code == 201
    assert resp.json()["data"]["count"] == 3


@pytest.mark.asyncio
async def test_replay_runs_are_queued_status(api_client) -> None:
    """All runs in the batch are returned with status QUEUED."""
    with patch("apps.api.routers.research_runs._celery_app") as mock_celery:
        mock_celery.send_task = MagicMock()
        resp = await api_client.post(
            "/api/v1/research-runs/historical-replay",
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-01-08",
                "symbols": ["AAPL"],
                "cadence": "weekly",
            },
        )

    assert resp.status_code == 201
    runs = resp.json()["data"]["runs"]
    for run in runs:
        assert run["status"] == "QUEUED"


@pytest.mark.asyncio
async def test_replay_symbols_normalized_uppercase(api_client) -> None:
    """Symbols are stored and returned uppercase."""
    with patch("apps.api.routers.research_runs._celery_app") as mock_celery:
        mock_celery.send_task = MagicMock()
        resp = await api_client.post(
            "/api/v1/research-runs/historical-replay",
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-01-01",
                "symbols": ["aapl", "nvda"],
                "cadence": "weekly",
            },
        )

    assert resp.status_code == 201
    run = resp.json()["data"]["runs"][0]
    assert "AAPL" in run["symbols"]
    assert "NVDA" in run["symbols"]
    assert "aapl" not in run["symbols"]


@pytest.mark.asyncio
async def test_replay_metadata_json_fields(api_client, db_session) -> None:
    """Each run's metadata_json contains all required historical_replay fields."""
    from db.models import ResearchRun

    with patch("apps.api.routers.research_runs._celery_app") as mock_celery:
        mock_celery.send_task = MagicMock()
        resp = await api_client.post(
            "/api/v1/research-runs/historical-replay",
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-01-08",
                "symbols": ["AAPL"],
                "cadence": "weekly",
            },
        )

    assert resp.status_code == 201
    data = resp.json()["data"]
    batch_id = data["replay_batch_id"]

    for run_info in data["runs"]:
        run_id = uuid.UUID(run_info["id"])
        run = await db_session.get(ResearchRun, run_id)
        assert run is not None
        meta = run.metadata_json
        assert meta["historical_replay"] is True
        assert meta["replay_batch_id"] == batch_id
        assert meta["as_of_date"] == run_info["as_of_date"]
        assert meta["source"] == "historical_graph_replay"
        assert meta["cadence"] == "weekly"
        # Must NOT have scenario_seed so REAL filter includes it
        assert "scenario_seed" not in meta


@pytest.mark.asyncio
async def test_replay_response_includes_replay_batch_id(api_client) -> None:
    """Response includes a stable replay_batch_id for all runs in the batch."""
    with patch("apps.api.routers.research_runs._celery_app") as mock_celery:
        mock_celery.send_task = MagicMock()
        resp = await api_client.post(
            "/api/v1/research-runs/historical-replay",
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-01-08",
                "symbols": ["AAPL"],
                "cadence": "weekly",
            },
        )

    assert resp.status_code == 201
    data = resp.json()["data"]
    assert "replay_batch_id" in data
    assert len(data["replay_batch_id"]) == 36  # UUID string


@pytest.mark.asyncio
async def test_replay_runs_visible_in_list(api_client) -> None:
    """Replay runs appear in GET /research-runs for the same user."""
    with patch("apps.api.routers.research_runs._celery_app") as mock_celery:
        mock_celery.send_task = MagicMock()
        replay_resp = await api_client.post(
            "/api/v1/research-runs/historical-replay",
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-01-08",
                "symbols": ["AAPL"],
                "cadence": "weekly",
            },
        )

    run_ids = {r["id"] for r in replay_resp.json()["data"]["runs"]}
    list_resp = await api_client.get("/api/v1/research-runs")
    listed_ids = {r["id"] for r in list_resp.json()["data"]}
    assert run_ids.issubset(listed_ids)


@pytest.mark.asyncio
async def test_replay_user_b_cannot_see_user_a_runs(api_client) -> None:
    """User B cannot access replay runs created by User A."""
    user_a = str(DEV_DEFAULT_USER_ID)
    user_b = str(uuid.uuid4())

    with patch("apps.api.routers.research_runs._celery_app") as mock_celery:
        mock_celery.send_task = MagicMock()
        resp = await api_client.post(
            "/api/v1/research-runs/historical-replay",
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-01-01",
                "symbols": ["AAPL"],
                "cadence": "weekly",
            },
            headers={"x-user-id": user_a},
        )

    run_id = resp.json()["data"]["runs"][0]["id"]
    check = await api_client.get(
        f"/api/v1/research-runs/{run_id}",
        headers={"x-user-id": user_b},
    )
    assert check.status_code == 404


# ── Validation tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replay_end_before_start_returns_422(api_client) -> None:
    """end_date before start_date returns 422."""
    resp = await api_client.post(
        "/api/v1/research-runs/historical-replay",
        json={
            "start_date": "2026-01-15",
            "end_date": "2026-01-01",
            "symbols": ["AAPL"],
            "cadence": "weekly",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_replay_too_many_runs_returns_422(api_client) -> None:
    """A range that would generate > 120 runs returns 422."""
    resp = await api_client.post(
        "/api/v1/research-runs/historical-replay",
        json={
            "start_date": "2020-01-01",
            "end_date": "2026-05-01",
            "symbols": ["AAPL"],
            "cadence": "daily",  # 6+ years daily = 2000+ runs
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_replay_async_false_returns_422(api_client) -> None:
    """async_execution=false is not supported for historical replay → 422."""
    resp = await api_client.post(
        "/api/v1/research-runs/historical-replay",
        json={
            "start_date": "2026-01-01",
            "end_date": "2026-01-08",
            "symbols": ["AAPL"],
            "cadence": "weekly",
            "async_execution": False,
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_replay_empty_symbols_returns_422(api_client) -> None:
    """Empty symbols list returns 422."""
    resp = await api_client.post(
        "/api/v1/research-runs/historical-replay",
        json={
            "start_date": "2026-01-01",
            "end_date": "2026-01-08",
            "symbols": [],
            "cadence": "weekly",
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_replay_invalid_cadence_returns_422(api_client) -> None:
    """Invalid cadence returns 422."""
    resp = await api_client.post(
        "/api/v1/research-runs/historical-replay",
        json={
            "start_date": "2026-01-01",
            "end_date": "2026-01-08",
            "symbols": ["AAPL"],
            "cadence": "quarterly",
        },
    )
    assert resp.status_code == 422


# ── Schema unit tests ──────────────────────────────────────────────────────────


def test_generate_replay_dates_weekly() -> None:
    """Weekly cadence generates correct dates."""
    from db.schemas import _generate_replay_dates

    dates = _generate_replay_dates(date(2026, 1, 1), date(2026, 1, 22), "weekly")
    assert dates == [date(2026, 1, 1), date(2026, 1, 8), date(2026, 1, 15), date(2026, 1, 22)]


def test_generate_replay_dates_daily() -> None:
    """Daily cadence generates correct dates."""
    from db.schemas import _generate_replay_dates

    dates = _generate_replay_dates(date(2026, 1, 1), date(2026, 1, 3), "daily")
    assert dates == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]


def test_generate_replay_dates_monthly() -> None:
    """Monthly cadence generates correct dates."""
    from db.schemas import _generate_replay_dates

    dates = _generate_replay_dates(date(2026, 1, 15), date(2026, 3, 15), "monthly")
    assert dates == [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)]


def test_generate_replay_dates_monthly_clamps_feb() -> None:
    """Monthly cadence clamps Jan-31 → Feb-28 (Feb has no 31st).
    After clamping, subsequent months continue from the clamped day (28),
    so March becomes Mar-28 (not Mar-31). This is intentional — simple and deterministic.
    """
    from db.schemas import _generate_replay_dates

    dates = _generate_replay_dates(date(2026, 1, 31), date(2026, 3, 31), "monthly")
    assert date(2026, 1, 31) in dates
    assert date(2026, 2, 28) in dates  # Feb clamp (no Feb 31)
    assert date(2026, 3, 28) in dates  # carries over clamped day


def test_generate_replay_dates_same_day() -> None:
    """Single-day range returns one date."""
    from db.schemas import _generate_replay_dates

    dates = _generate_replay_dates(date(2026, 1, 15), date(2026, 1, 15), "weekly")
    assert dates == [date(2026, 1, 15)]


# ── Dispatch / error handling tests ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replay_uses_celery_send_task_not_delay(api_client) -> None:
    """Replay endpoint dispatches via celery_app.send_task(), not task.delay()."""
    with patch("apps.api.routers.research_runs._celery_app") as mock_celery:
        mock_celery.send_task = MagicMock()
        resp = await api_client.post(
            "/api/v1/research-runs/historical-replay",
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-01-08",
                "symbols": ["AAPL"],
                "cadence": "weekly",
            },
        )

    assert resp.status_code == 201
    data = resp.json()["data"]
    # 2 weekly dates: Jan 1, Jan 8
    assert mock_celery.send_task.call_count == data["count"]
    # Every call must use the correct task name
    for call in mock_celery.send_task.call_args_list:
        assert call[0][0] == "apps.worker.tasks.research.run_research_run_task"


@pytest.mark.asyncio
async def test_replay_enqueue_failure_returns_503(api_client) -> None:
    """If Celery dispatch fails, endpoint returns 503 with a safe message.
    Response must not contain broker URL, Redis URL, or stack trace."""
    with patch("apps.api.routers.research_runs._celery_app") as mock_celery:
        mock_celery.send_task = MagicMock(side_effect=ConnectionRefusedError("redis down"))

        resp = await api_client.post(
            "/api/v1/research-runs/historical-replay",
            json={
                "start_date": "2026-01-01",
                "end_date": "2026-01-01",
                "symbols": ["AAPL"],
                "cadence": "weekly",
            },
        )

    assert resp.status_code == 503
    body = resp.json()
    detail = body.get("detail", "")
    assert "queue" in detail.lower() or "retry" in detail.lower()
    assert "redis" not in detail.lower()
    assert "ConnectionRefusedError" not in detail
    assert "redis down" not in detail
