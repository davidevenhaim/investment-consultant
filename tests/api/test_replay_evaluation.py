"""Tests for POST /api/v1/research-runs/historical-replay/{id}/evaluation — M12.8."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from apps.api.dependencies.auth import DEV_DEFAULT_USER_ID

# ── Seed helpers ───────────────────────────────────────────────────────────────


async def _seed_replay_run(
    db_session: Any,
    *,
    user_id: uuid.UUID,
    replay_batch_id: str,
    as_of_date: str,
    status: str = "COMPLETED",
    symbols: list[str] | None = None,
) -> Any:
    from db.models import ResearchRun, ResearchRunTicker

    run = ResearchRun(
        id=uuid.uuid4(),
        user_id=user_id,
        run_type="HISTORICAL_REPLAY",
        status=status,
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
    for sym in symbols or ["AAPL"]:
        db_session.add(ResearchRunTicker(research_run_id=run.id, symbol=sym, status="CREATED"))
    await db_session.flush()
    return run


async def _seed_replay_batch(
    db_session: Any,
    *,
    user_id: uuid.UUID,
    replay_batch_id: str,
    dates_and_statuses: list[tuple[str, str]],
    symbols: list[str] | None = None,
) -> list[Any]:
    runs = []
    for as_of_date, status in dates_and_statuses:
        run = await _seed_replay_run(
            db_session,
            user_id=user_id,
            replay_batch_id=replay_batch_id,
            as_of_date=as_of_date,
            status=status,
            symbols=symbols,
        )
        runs.append(run)
    return runs


async def _seed_neutral_rec(
    db_session: Any,
    *,
    run_id: uuid.UUID,
    symbol: str = "AAPL",
    action: str = "HOLD",
    score: int = 55,
    score_breakdown: dict[str, Any] | None = None,
    price: float = 150.0,
) -> Any:
    from db.models import NeutralRecommendation

    rec = NeutralRecommendation(
        research_run_id=run_id,
        symbol=symbol.upper(),
        action=action,
        score=score,
        confidence=0.8,
        score_breakdown_json=score_breakdown or {"technical": 12.0},
        what_changed_json=[],
        main_reasons_json=[],
        main_risks_json=[],
        missing_details_json=[],
        final_reason="test",
        as_of_time=datetime.now(UTC),
        price_at_recommendation=price,
    )
    db_session.add(rec)
    await db_session.flush()
    return rec


async def _seed_personalized_rec(
    db_session: Any,
    *,
    neutral_id: uuid.UUID,
    symbol: str = "AAPL",
    personal_action: str = "HOLD",
) -> Any:
    from db.models import PersonalizedRecommendation

    rec = PersonalizedRecommendation(
        neutral_recommendation_id=neutral_id,
        symbol=symbol.upper(),
        personal_action=personal_action,
        position_sizing_json={},
        policy_checks_json=[],
        personal_reason="test",
        symbol_trading_stats_json={},
    )
    db_session.add(rec)
    await db_session.flush()
    return rec


# ── Error path tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluation_unknown_batch_returns_404(api_client) -> None:
    """Unknown replay_batch_id → 404."""
    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{uuid.uuid4()}/evaluation",
        json={"initial_cash": 10000},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_evaluation_another_users_batch_returns_404(api_client, db_session) -> None:
    """Batch belonging to a different user → 404 (not 403)."""
    other_user = uuid.uuid4()
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=other_user,
        replay_batch_id=batch_id,
        dates_and_statuses=[("2025-01-01", "COMPLETED")],
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/evaluation",
        json={"initial_cash": 10000},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_evaluation_no_completed_runs_returns_422(api_client, db_session) -> None:
    """Batch with no COMPLETED runs → 422."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2025-01-01", "QUEUED"),
            ("2025-01-08", "FAILED"),
        ],
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/evaluation",
        json={"initial_cash": 10000},
    )
    assert resp.status_code == 422
    assert "completed" in resp.json()["detail"].lower()


# ── Happy path ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluation_happy_path_top_level_shape(api_client, db_session) -> None:
    """Completed batch returns evaluation with all required top-level keys."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2025-01-01", "COMPLETED"),
            ("2025-01-08", "COMPLETED"),
        ],
        symbols=["AAPL"],
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/evaluation",
        json={"initial_cash": 10000, "benchmark_symbol": "SPY"},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]

    assert data["replay_batch_id"] == batch_id
    assert "backtest_run_id" in data
    assert "date_range" in data
    assert "symbols" in data
    assert "run_counts" in data
    assert "portfolio_result" in data
    assert "symbol_evaluations" in data
    assert "highlights" in data


@pytest.mark.asyncio
async def test_evaluation_date_range_derived_from_batch(api_client, db_session) -> None:
    """date_range reflects the min/max as_of_date of completed runs."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2025-01-01", "COMPLETED"),
            ("2025-01-15", "COMPLETED"),
            ("2025-01-08", "COMPLETED"),
        ],
        symbols=["AAPL"],
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/evaluation",
        json={"initial_cash": 5000},
    )
    assert resp.status_code == 201
    dr = resp.json()["data"]["date_range"]
    assert dr["start_date"] == "2025-01-01"
    assert dr["end_date"] == "2025-01-15"


@pytest.mark.asyncio
async def test_evaluation_run_counts_shape(api_client, db_session) -> None:
    """run_counts reflects total / completed / failed / queued / running."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2025-01-01", "COMPLETED"),
            ("2025-01-08", "COMPLETED"),
            ("2025-01-15", "FAILED"),
        ],
        symbols=["AAPL"],
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/evaluation",
        json={"initial_cash": 10000},
    )
    assert resp.status_code == 201
    rc = resp.json()["data"]["run_counts"]
    assert rc["total"] == 3
    assert rc["completed"] == 2
    assert rc["failed"] == 1
    assert rc["queued"] == 0
    assert rc["running"] == 0


@pytest.mark.asyncio
async def test_evaluation_symbol_evaluations_contain_report_summary(api_client, db_session) -> None:
    """symbol_evaluations preserve timeline summary fields from the report."""
    batch_id = str(uuid.uuid4())
    runs = await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2025-01-01", "COMPLETED"),
            ("2025-01-08", "COMPLETED"),
        ],
        symbols=["AAPL"],
    )

    # Seed neutral recs with different scores so timeline summary has real data
    await _seed_neutral_rec(db_session, run_id=runs[0].id, symbol="AAPL", score=50, action="HOLD")
    await _seed_neutral_rec(
        db_session, run_id=runs[1].id, symbol="AAPL", score=70, action="BUY_CANDIDATE"
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/evaluation",
        json={"initial_cash": 10000},
    )
    assert resp.status_code == 201
    evals = resp.json()["data"]["symbol_evaluations"]
    assert len(evals) == 1
    ev = evals[0]
    assert ev["symbol"] == "AAPL"
    assert "first_action" in ev
    assert "last_action" in ev
    assert "score_change" in ev
    assert "largest_score_move" in ev
    assert "trade_count" in ev
    assert "skip_count" in ev
    assert "advisor_behavior" in ev


@pytest.mark.asyncio
async def test_evaluation_highlights_deterministic(api_client, db_session) -> None:
    """highlights field is present and deterministic."""
    batch_id = str(uuid.uuid4())
    runs = await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2025-01-01", "COMPLETED"),
        ],
        symbols=["AAPL", "NVDA"],
    )
    await _seed_neutral_rec(db_session, run_id=runs[0].id, symbol="AAPL", score=60)
    await _seed_neutral_rec(db_session, run_id=runs[0].id, symbol="NVDA", score=40)

    resp1 = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/evaluation",
        json={"initial_cash": 10000},
    )
    resp2 = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/evaluation",
        json={"initial_cash": 10000},
    )
    assert resp1.status_code == 201
    assert resp2.status_code == 201

    h1 = resp1.json()["data"]["highlights"]
    h2 = resp2.json()["data"]["highlights"]
    # All deterministic highlight keys must agree
    for key in ("best_symbol", "worst_symbol", "most_active_symbol", "most_common_skip_reason"):
        assert h1[key] == h2[key], f"highlights[{key!r}] differs between two identical calls"


@pytest.mark.asyncio
async def test_evaluation_traceability_in_backtest(api_client, db_session) -> None:
    """Backtest created by evaluation has source=replay_batch_evaluation in assumptions."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[("2025-01-01", "COMPLETED")],
        symbols=["AAPL"],
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/evaluation",
        json={"initial_cash": 10000},
    )
    assert resp.status_code == 201
    data = resp.json()["data"]

    # backtest_run_id must be a valid UUID string
    assert uuid.UUID(data["backtest_run_id"])

    # Verify traceability using the shared test session (commit=flush in tests;
    # a new independent session would not see the unflushed row).
    from db.models import AdvisorBacktestRun
    from sqlalchemy import select

    result = await db_session.execute(
        select(AdvisorBacktestRun).where(
            AdvisorBacktestRun.id == uuid.UUID(data["backtest_run_id"])
        )
    )
    bt = result.scalar_one()

    assert bt.assumptions_json["source"] == "replay_batch_evaluation"
    assert bt.assumptions_json["replay_batch_id"] == batch_id


@pytest.mark.asyncio
async def test_evaluation_only_completed_runs_used(api_client, db_session) -> None:
    """Mixed-status batch: only COMPLETED runs feed the backtest."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[
            ("2025-01-01", "COMPLETED"),
            ("2025-01-08", "QUEUED"),  # not finished
            ("2025-01-15", "FAILED"),
        ],
        symbols=["AAPL"],
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/evaluation",
        json={"initial_cash": 10000},
    )
    assert resp.status_code == 201
    rc = resp.json()["data"]["run_counts"]
    assert rc["completed"] == 1
    assert rc["total"] == 3


@pytest.mark.asyncio
async def test_evaluation_with_initial_positions(api_client, db_session) -> None:
    """initial_positions accepted and passed to the backtest without errors."""
    import datetime as _dt

    from db.models import MarketPrice

    batch_id = str(uuid.uuid4())
    runs = await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[("2025-01-01", "COMPLETED")],
        symbols=["AAPL"],
    )
    await _seed_neutral_rec(db_session, run_id=runs[0].id, symbol="AAPL", action="REDUCE", score=35)

    # Seed a price bar so initial_positions can be priced (2025-01-02 is within the
    # 5-day forward tolerance from the start_date 2025-01-01).
    db_session.add(
        MarketPrice(
            symbol="AAPL",
            price_date=_dt.date(2025, 1, 2),
            open=150.0,
            high=155.0,
            low=149.0,
            close=152.0,
            adjusted_close=152.0,
            volume=1000000,
        )
    )
    await db_session.flush()

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/evaluation",
        json={
            "initial_cash": 10000,
            "initial_positions": [{"symbol": "AAPL", "quantity": 10}],
        },
    )
    # 201 — position is priced from seeded bar, no 422
    assert resp.status_code == 201


@pytest.mark.asyncio
async def test_evaluation_portfolio_result_shape(api_client, db_session) -> None:
    """portfolio_result contains all required keys."""
    batch_id = str(uuid.uuid4())
    await _seed_replay_batch(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        dates_and_statuses=[("2025-01-01", "COMPLETED")],
        symbols=["AAPL"],
    )

    resp = await api_client.post(
        f"/api/v1/research-runs/historical-replay/{batch_id}/evaluation",
        json={"initial_cash": 5000, "benchmark_symbol": "SPY"},
    )
    assert resp.status_code == 201
    pr = resp.json()["data"]["portfolio_result"]
    for key in (
        "initial_cash",
        "final_equity",
        "total_return_pct",
        "benchmark_symbol",
        "benchmark_return_pct",
        "relative_return_pct",
        "max_drawdown_pct",
        "total_trades",
        "winning_trades",
        "losing_trades",
        "trade_breakdown",
        "skip_breakdown",
        "recommendations_considered",
    ):
        assert key in pr, f"Missing key: {key!r}"

    assert pr["initial_cash"] == 5000
    assert pr["benchmark_symbol"] == "SPY"
