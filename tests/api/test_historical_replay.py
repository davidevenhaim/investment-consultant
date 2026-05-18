"""Tests for /api/v1/research-runs/historical-replay (M12.1 + M12.4)."""

import uuid
from datetime import UTC, date, datetime, timedelta
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


# ── M12.4: GET /historical-replay/{replay_batch_id} ──────────────────────────


async def _seed_replay_batch(
    db_session: object,
    *,
    user_id: uuid.UUID,
    replay_batch_id: str,
    dates_and_statuses: list[tuple[str, str]],
    symbols: list[str] | None = None,
) -> None:
    """Seed replay runs directly into the DB for batch-status tests."""
    from db.models import ResearchRun, ResearchRunTicker

    syms = symbols or ["AAPL"]
    for as_of_date, status in dates_and_statuses:
        run = ResearchRun(
            id=uuid.uuid4(),
            user_id=user_id,
            run_type="HISTORICAL_REPLAY",
            status=status,
            metadata_json={
                "historical_replay": True,
                "replay_batch_id": replay_batch_id,
                "as_of_date": as_of_date,
                "source": "historical_graph_replay",
                "cadence": "weekly",
            },
            created_at=datetime.now(UTC),
        )
        db_session.add(run)  # type: ignore[attr-defined]
        await db_session.flush()  # type: ignore[attr-defined]
        for sym in syms:
            db_session.add(ResearchRunTicker(  # type: ignore[attr-defined]
                research_run_id=run.id, symbol=sym, status="CREATED"
            ))
        await db_session.flush()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_replay_batch_status_returns_all_runs(api_client, db_session) -> None:
    """GET /historical-replay/{id} returns every run in the batch."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2026-01-01", "COMPLETED"),
            ("2026-01-08", "COMPLETED"),
            ("2026-01-15", "QUEUED"),
        ],
    )

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["replay_batch_id"] == batch_id
    assert data["total"] == 3
    assert len(data["runs"]) == 3


@pytest.mark.asyncio
async def test_replay_batch_status_counts_by_status(api_client, db_session) -> None:
    """counts dict reflects actual status distribution."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2026-01-01", "COMPLETED"),
            ("2026-01-08", "FAILED"),
            ("2026-01-15", "QUEUED"),
            ("2026-01-22", "COMPLETED"),
        ],
    )

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    assert resp.status_code == 200
    counts = resp.json()["data"]["counts"]
    assert counts["COMPLETED"] == 2
    assert counts["FAILED"] == 1
    assert counts["QUEUED"] == 1


@pytest.mark.asyncio
async def test_replay_batch_status_ordered_by_as_of_date(api_client, db_session) -> None:
    """Runs in response are ordered by as_of_date ascending regardless of insert order."""
    batch_id = str(uuid.uuid4())
    # Insert in reverse order
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2026-01-22", "QUEUED"),
            ("2026-01-01", "COMPLETED"),
            ("2026-01-08", "FAILED"),
        ],
    )

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    assert resp.status_code == 200
    dates = [r["as_of_date"] for r in resp.json()["data"]["runs"]]
    assert dates == ["2026-01-01", "2026-01-08", "2026-01-22"]


@pytest.mark.asyncio
async def test_replay_batch_status_run_fields(api_client, db_session) -> None:
    """Each run item contains id, as_of_date, status, symbols, created_at."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[("2026-01-01", "COMPLETED")],
        symbols=["AAPL", "NVDA"],
    )

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    assert resp.status_code == 200
    run = resp.json()["data"]["runs"][0]
    assert "id" in run
    assert run["as_of_date"] == "2026-01-01"
    assert run["status"] == "COMPLETED"
    assert set(run["symbols"]) == {"AAPL", "NVDA"}
    assert "created_at" in run
    assert "started_at" in run
    assert "finished_at" in run


@pytest.mark.asyncio
async def test_replay_batch_status_unknown_batch_returns_404(api_client) -> None:
    """Unknown replay_batch_id → 404."""
    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{uuid.uuid4()}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_replay_batch_status_user_isolation(
    api_client, db_session, monkeypatch
) -> None:
    """User B cannot see User A's replay batch."""
    batch_id = str(uuid.uuid4())
    other_user = uuid.uuid4()

    await _seed_replay_batch(
        db_session,
        user_id=other_user,
        replay_batch_id=batch_id,
        dates_and_statuses=[("2026-01-01", "COMPLETED")],
    )

    # api_client authenticates as DEV_DEFAULT_USER_ID (not other_user)
    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    assert resp.status_code == 404


# ── M12.6: enriched GET /historical-replay/{replay_batch_id} fields ──────────


@pytest.mark.asyncio
async def test_replay_batch_progress_zero_when_no_terminal(api_client, db_session) -> None:
    """progress_pct is 0.0 when no runs are in a terminal state."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[("2026-01-01", "QUEUED"), ("2026-01-08", "RUNNING")],
    )
    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["progress_pct"] == 0.0
    assert data["completed_count"] == 0
    assert data["failed_count"] == 0


@pytest.mark.asyncio
async def test_replay_batch_progress_100_when_all_terminal(api_client, db_session) -> None:
    """progress_pct reaches 100.0 when every run is COMPLETED or FAILED."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2026-01-01", "COMPLETED"),
            ("2026-01-08", "FAILED"),
        ],
    )
    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    data = resp.json()["data"]
    assert data["progress_pct"] == 100.0
    assert data["completed_count"] == 1
    assert data["failed_count"] == 1


@pytest.mark.asyncio
async def test_replay_batch_progress_mixed(api_client, db_session) -> None:
    """progress_pct is partial when some runs are terminal, some are not."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2026-01-01", "COMPLETED"),
            ("2026-01-08", "QUEUED"),
            ("2026-01-15", "QUEUED"),
            ("2026-01-22", "QUEUED"),
        ],
    )
    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    data = resp.json()["data"]
    assert data["progress_pct"] == 25.0
    assert data["queued_count"] == 3
    assert data["running_count"] == 0


@pytest.mark.asyncio
async def test_replay_batch_first_last_as_of_date(api_client, db_session) -> None:
    """first_as_of_date and last_as_of_date reflect min and max dates in the batch."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2026-01-22", "QUEUED"),
            ("2026-01-01", "COMPLETED"),
            ("2026-01-08", "FAILED"),
        ],
    )
    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    data = resp.json()["data"]
    assert data["first_as_of_date"] == "2026-01-01"
    assert data["last_as_of_date"] == "2026-01-22"


@pytest.mark.asyncio
async def test_replay_batch_started_finished_aggregate(api_client, db_session) -> None:
    """started_at is earliest; finished_at is latest across all runs that have them."""
    from db.models import ResearchRun, ResearchRunTicker

    batch_id = str(uuid.uuid4())
    t_early = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)
    t_late = datetime(2026, 1, 1, 17, 0, 0, tzinfo=UTC)

    for _i, (aod, sta, fna) in enumerate([
        ("2026-01-01", t_early, t_late),
        ("2026-01-08", t_late, None),
    ]):
        run = ResearchRun(
            id=uuid.uuid4(),
            user_id=DEV_DEFAULT_USER_ID,
            run_type="HISTORICAL_REPLAY",
            status="COMPLETED" if fna else "RUNNING",
            started_at=sta,
            finished_at=fna,
            metadata_json={
                "historical_replay": True,
                "replay_batch_id": batch_id,
                "as_of_date": aod,
                "cadence": "weekly",
            },
            created_at=datetime.now(UTC),
        )
        db_session.add(run)
        await db_session.flush()
        db_session.add(ResearchRunTicker(research_run_id=run.id, symbol="AAPL", status="CREATED"))
        await db_session.flush()

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    data = resp.json()["data"]
    assert data["started_at"] is not None
    assert "2026-01-01T09:00:00" in data["started_at"]
    assert data["finished_at"] is not None
    assert "2026-01-01T17:00:00" in data["finished_at"]
    assert data["elapsed_seconds"] is not None
    assert data["elapsed_seconds"] > 0


@pytest.mark.asyncio
async def test_replay_batch_backwards_compat_counts_dict(api_client, db_session) -> None:
    """Legacy 'counts' dict is still present in the response."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[("2026-01-01", "COMPLETED")],
    )
    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    data = resp.json()["data"]
    assert "counts" in data
    assert isinstance(data["counts"], dict)
    assert data["counts"].get("COMPLETED") == 1


# ── M12.5: POST /historical-replay/{replay_batch_id}/backtest ─────────────────


@pytest.mark.asyncio
async def test_replay_batch_backtest_unknown_batch_returns_404(api_client) -> None:
    """Unknown replay_batch_id → 404."""
    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{uuid.uuid4()}/backtest",
        json={"initial_cash": 10000},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_replay_batch_backtest_no_completed_runs_returns_422(
    api_client, db_session
) -> None:
    """Batch with no COMPLETED runs → 422."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2026-01-01", "QUEUED"),
            ("2026-01-08", "FAILED"),
            ("2026-01-15", "RUNNING"),
        ],
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/backtest",
        json={"initial_cash": 10000},
    )
    assert resp.status_code == 422
    assert "completed" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_replay_batch_backtest_creates_advisor_backtest(
    api_client, db_session
) -> None:
    """Completed batch → 201 with AdvisorBacktestRunDetailResponse shape."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2026-01-01", "COMPLETED"),
            ("2026-01-08", "COMPLETED"),
        ],
        symbols=["AAPL"],
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/backtest",
        json={"initial_cash": 10000, "benchmark_symbol": "SPY"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    # Shape matches AdvisorBacktestRunDetailResponse
    assert "id" in data
    assert "status" in data
    assert "initial_cash" in data
    assert data["initial_cash"] == 10000
    assert "trades" in data
    assert "equity_points" in data


@pytest.mark.asyncio
async def test_replay_batch_backtest_only_completed_runs_used(
    api_client, db_session
) -> None:
    """Batch with mixed statuses: only COMPLETED runs are fed into the backtest."""
    batch_id = str(uuid.uuid4())
    # 2 completed, 1 queued — should succeed (not 422)
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2026-01-01", "COMPLETED"),
            ("2026-01-08", "QUEUED"),   # not yet done
            ("2026-01-15", "COMPLETED"),
        ],
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/backtest",
        json={"initial_cash": 5000},
    )
    # Succeeds because there are COMPLETED runs
    assert resp.status_code == 201
    data = resp.json()["data"]
    # summary_json must show completed_run_count=2, not 3
    assumptions = data.get("assumptions_json", {})
    assert assumptions.get("completed_run_count") == 2
    assert assumptions.get("total_run_count") == 3


@pytest.mark.asyncio
async def test_replay_batch_backtest_user_isolation(api_client, db_session) -> None:
    """User B cannot backtest User A's replay batch → 404."""
    batch_id = str(uuid.uuid4())
    other_user = uuid.uuid4()
    await _seed_replay_batch(
        db_session,
        user_id=other_user,
        replay_batch_id=batch_id,
        dates_and_statuses=[("2026-01-01", "COMPLETED")],
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/backtest",
        json={"initial_cash": 10000},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_replay_batch_backtest_traceability(api_client, db_session) -> None:
    """replay_batch_id appears in assumptions_json and summary_json for traceability."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[("2026-01-01", "COMPLETED")],
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/backtest",
        json={"initial_cash": 10000},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]

    assumptions = data.get("assumptions_json", {})
    assert assumptions.get("replay_batch_id") == batch_id
    assert assumptions.get("source") == "replay_batch_backtest"

    summary = data.get("summary_json", {})
    assert summary.get("replay_batch_id") == batch_id or assumptions.get("replay_batch_id") == batch_id


# ── elapsed_seconds guard tests ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_elapsed_seconds_null_when_finished_at_backdated(
    api_client, db_session
) -> None:
    """Replay runs with backdated finished_at must return elapsed_seconds=null."""
    from db.models import ResearchRun, ResearchRunTicker

    batch_id = str(uuid.uuid4())
    # started_at is real wall-clock; finished_at is backdated to replay as_of_date
    wall_clock = datetime(2026, 5, 17, 12, 52, 30, tzinfo=UTC)
    backdated = datetime(2026, 1, 1, 16, 0, 0, tzinfo=UTC)

    run = ResearchRun(
        id=uuid.uuid4(),
        user_id=DEV_DEFAULT_USER_ID,
        run_type="HISTORICAL_REPLAY",
        status="COMPLETED",
        started_at=wall_clock,
        finished_at=backdated,
        metadata_json={
            "historical_replay": True,
            "replay_batch_id": batch_id,
            "as_of_date": "2026-01-01",
            "cadence": "weekly",
        },
        created_at=datetime.now(UTC),
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add(ResearchRunTicker(research_run_id=run.id, symbol="AAPL", status="CREATED"))
    await db_session.flush()

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    data = resp.json()["data"]
    # started_at and finished_at must be preserved as-is
    assert "2026-05-17T12:52:30" in data["started_at"]
    assert "2026-01-01T16:00:00" in data["finished_at"]
    # elapsed must be null — not negative
    assert data["elapsed_seconds"] is None


@pytest.mark.asyncio
async def test_elapsed_seconds_positive_for_running_batch(
    api_client, db_session
) -> None:
    """In-progress batch (no finished_at) returns positive elapsed_seconds."""
    from db.models import ResearchRun, ResearchRunTicker

    batch_id = str(uuid.uuid4())
    # started_at well in the past so elapsed > 0
    past = datetime(2026, 1, 1, 9, 0, 0, tzinfo=UTC)

    run = ResearchRun(
        id=uuid.uuid4(),
        user_id=DEV_DEFAULT_USER_ID,
        run_type="HISTORICAL_REPLAY",
        status="RUNNING",
        started_at=past,
        finished_at=None,
        metadata_json={
            "historical_replay": True,
            "replay_batch_id": batch_id,
            "as_of_date": "2026-01-01",
            "cadence": "weekly",
        },
        created_at=datetime.now(UTC),
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add(ResearchRunTicker(research_run_id=run.id, symbol="AAPL", status="CREATED"))
    await db_session.flush()

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    data = resp.json()["data"]
    assert data["finished_at"] is None
    assert data["elapsed_seconds"] is not None
    assert data["elapsed_seconds"] > 0


@pytest.mark.asyncio
async def test_elapsed_seconds_positive_when_not_backdated(
    api_client, db_session
) -> None:
    """Normal completed batch (started_at < finished_at) still returns positive elapsed."""
    from db.models import ResearchRun, ResearchRunTicker

    batch_id = str(uuid.uuid4())
    t_start = datetime(2026, 5, 17, 12, 0, 0, tzinfo=UTC)
    t_end = datetime(2026, 5, 17, 12, 3, 45, tzinfo=UTC)

    run = ResearchRun(
        id=uuid.uuid4(),
        user_id=DEV_DEFAULT_USER_ID,
        run_type="HISTORICAL_REPLAY",
        status="COMPLETED",
        started_at=t_start,
        finished_at=t_end,
        metadata_json={
            "historical_replay": True,
            "replay_batch_id": batch_id,
            "as_of_date": "2026-05-17",
            "cadence": "weekly",
        },
        created_at=datetime.now(UTC),
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add(ResearchRunTicker(research_run_id=run.id, symbol="AAPL", status="CREATED"))
    await db_session.flush()

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}")
    data = resp.json()["data"]
    assert data["elapsed_seconds"] == 225.0  # 3m45s


# ── initial_positions tests ────────────────────────────────────────────────────


async def _seed_replay_run_with_neutral_rec(
    db_session,
    *,
    user_id: uuid.UUID,
    replay_batch_id: str,
    as_of_date: str,
    symbol: str,
    action: str,
) -> tuple:
    """Seed a COMPLETED replay run + neutral recommendation. Returns (run, rec)."""
    from db.models import NeutralRecommendation, ResearchRun, ResearchRunTicker

    rec_dt = datetime.fromisoformat(f"{as_of_date}T16:00:00").replace(tzinfo=UTC)
    run = ResearchRun(
        id=uuid.uuid4(),
        user_id=user_id,
        run_type="HISTORICAL_REPLAY",
        status="COMPLETED",
        started_at=rec_dt,
        finished_at=rec_dt,
        metadata_json={
            "historical_replay": True,
            "replay_batch_id": replay_batch_id,
            "as_of_date": as_of_date,
            "cadence": "weekly",
        },
        created_at=datetime.now(UTC),
    )
    db_session.add(run)
    await db_session.flush()
    db_session.add(ResearchRunTicker(research_run_id=run.id, symbol=symbol, status="CREATED"))
    await db_session.flush()

    nr = NeutralRecommendation(
        research_run_id=run.id,
        symbol=symbol.upper(),
        action=action,
        score=40,
        confidence=0.75,
        final_reason="test",
        score_breakdown_json={},
        main_reasons_json=[],
        main_risks_json=[],
        missing_details_json=[],
        what_changed_json=[],
        as_of_time=rec_dt,
        price_at_recommendation=100.0,
    )
    nr.created_at = rec_dt  # type: ignore[assignment]
    db_session.add(nr)
    await db_session.flush()
    return run, nr


async def _seed_market_price_rows(
    db_session,
    symbol: str,
    start: date,
    n: int = 30,
    price: float = 100.0,
) -> None:
    from db.models import MarketPrice

    d = start
    rows = []
    for _ in range(n):
        while d.weekday() >= 5:
            d += timedelta(days=1)
        rows.append(MarketPrice(
            symbol=symbol.upper(),
            price_date=d,
            open=price,
            high=price,
            low=price,
            close=price,
            adjusted_close=price,
            volume=1_000_000,
            provider="yfinance",
        ))
        d += timedelta(days=1)
    db_session.add_all(rows)
    await db_session.flush()


@pytest.mark.asyncio
async def test_initial_positions_backwards_compatible(api_client, db_session) -> None:
    """Request without initial_positions behaves exactly as before."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[("2026-01-05", "COMPLETED")],
    )
    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/backtest",
        json={"initial_cash": 10000},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]
    assert data["initial_cash"] == 10000
    assert "initial_positions" not in (data.get("assumptions_json") or {})


@pytest.mark.asyncio
async def test_initial_positions_reduce_executes_not_skipped(
    api_client, db_session
) -> None:
    """REDUCE recommendation with a seeded position creates a REDUCE trade, not a SKIP."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_run_with_neutral_rec(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-05",
        symbol="AAPL",
        action="REDUCE",
    )
    await _seed_market_price_rows(db_session, "AAPL", date(2026, 1, 5), n=30, price=100.0)

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/backtest",
        json={
            "initial_cash": 50000,
            "initial_positions": [{"symbol": "AAPL", "quantity": 100}],
        },
    )
    assert resp.status_code == 201
    trades = resp.json()["data"]["trades"]
    reduce_trades = [t for t in trades if t["trade_type"] == "REDUCE"]
    skip_no_pos = [
        t for t in trades
        if t["trade_type"] == "SKIP" and t.get("reason") == "no_position_to_reduce"
    ]
    assert len(reduce_trades) >= 1, "Expected at least one REDUCE trade"
    assert len(skip_no_pos) == 0, "Should not have no_position_to_reduce SKIPs"


@pytest.mark.asyncio
async def test_initial_positions_in_assumptions_json(api_client, db_session) -> None:
    """initial_positions are captured in assumptions_json with entry_price."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_run_with_neutral_rec(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-05",
        symbol="AAPL",
        action="HOLD",
    )
    await _seed_market_price_rows(db_session, "AAPL", date(2026, 1, 5), n=30, price=150.0)

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/backtest",
        json={
            "initial_cash": 50000,
            "initial_positions": [{"symbol": "AAPL", "quantity": 50}],
        },
    )
    assert resp.status_code == 201
    assumptions = resp.json()["data"]["assumptions_json"]
    assert "initial_positions" in assumptions
    ip = assumptions["initial_positions"]
    assert len(ip) == 1
    assert ip[0]["symbol"] == "AAPL"
    assert ip[0]["quantity"] == 50
    assert ip[0]["entry_price"] == 150.0


@pytest.mark.asyncio
async def test_initial_positions_closed_position_in_summary(
    api_client, db_session
) -> None:
    """After a REDUCE on a seeded position, closed_positions appears in summary_json."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_run_with_neutral_rec(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-05",
        symbol="TSLA",
        action="REDUCE",
    )
    await _seed_market_price_rows(db_session, "TSLA", date(2026, 1, 5), n=30, price=200.0)

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/backtest",
        json={
            "initial_cash": 100000,
            "initial_positions": [{"symbol": "TSLA", "quantity": 50}],
        },
    )
    assert resp.status_code == 201
    summary = resp.json()["data"]["summary_json"]
    closed = summary.get("closed_positions", [])
    symbols_closed = [c["symbol"] for c in closed]
    assert "TSLA" in symbols_closed


@pytest.mark.asyncio
async def test_initial_positions_cost_exceeds_cash_returns_422(
    api_client, db_session
) -> None:
    """Total initial position cost > initial_cash → 422."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_run_with_neutral_rec(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-05",
        symbol="AAPL",
        action="HOLD",
    )
    # Price 100, quantity 500 → cost $50,000 > initial_cash $10,000
    await _seed_market_price_rows(db_session, "AAPL", date(2026, 1, 5), n=10, price=100.0)

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/backtest",
        json={
            "initial_cash": 10000,
            "initial_positions": [{"symbol": "AAPL", "quantity": 500}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_initial_positions_unpriceable_symbol_returns_422(
    api_client, db_session
) -> None:
    """Symbol with no market price bars → 422 (not 500)."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_run_with_neutral_rec(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-05",
        symbol="AAPL",
        action="HOLD",
    )
    # No market data seeded for UNKNWN

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/backtest",
        json={
            "initial_cash": 50000,
            "initial_positions": [{"symbol": "UNKNWN", "quantity": 10}],
        },
    )
    assert resp.status_code == 422
