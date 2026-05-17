"""Integration test: historical replay recommendations are included in advisor backtests.

Verifies:
1. A completed historical replay run with as_of_date inside the backtest window is
   included when recommendation_source=REAL.
2. A scenario-seeded run is excluded when recommendation_source=REAL.
3. A completed historical replay run with as_of_date outside the window is excluded.
"""

import uuid
from datetime import UTC, datetime

import pytest

from apps.api.dependencies.auth import DEV_DEFAULT_USER_ID

# ── Helpers ────────────────────────────────────────────────────────────────────


async def _seed_replay_rec(
    db_session,
    *,
    as_of_date_str: str,
    action: str = "HOLD",
    symbol: str = "AAPL",
):
    """Create a completed HISTORICAL_REPLAY run with one NeutralRecommendation,
    timestamps back-dated to as_of_date 16:00 UTC (as the worker would do)."""
    from datetime import date

    from db.models import NeutralRecommendation, ResearchRun, ResearchRunTicker

    as_of_date = date.fromisoformat(as_of_date_str)
    ts = datetime(as_of_date.year, as_of_date.month, as_of_date.day, 16, 0, 0, tzinfo=UTC)

    run_id = uuid.uuid4()
    run = ResearchRun(
        id=run_id,
        user_id=DEV_DEFAULT_USER_ID,
        run_type="HISTORICAL_REPLAY",
        status="COMPLETED",
        finished_at=ts,  # back-dated, as worker would do for replay
        metadata_json={
            "historical_replay": True,
            "replay_batch_id": str(uuid.uuid4()),
            "as_of_date": as_of_date_str,
            "source": "historical_graph_replay",
            "cadence": "weekly",
        },
    )
    db_session.add(run)
    await db_session.flush()

    ticker = ResearchRunTicker(
        research_run_id=run_id,
        symbol=symbol,
        status="COMPLETED",
    )
    db_session.add(ticker)
    await db_session.flush()

    nr = NeutralRecommendation(
        research_run_id=run_id,
        research_run_ticker_id=ticker.id,
        symbol=symbol,
        action=action,
        score=60,
        confidence=0.7,
        as_of_time=ts,
        created_at=ts,  # explicitly set to replay date
        score_breakdown_json={},
        what_changed_json=[],
        main_reasons_json=[],
        main_risks_json=[],
        missing_details_json=[],
        final_reason="test",
        data_quality_score=0.9,
    )
    db_session.add(nr)
    await db_session.flush()
    return run, nr


async def _seed_scenario_rec(db_session, *, as_of_date_str: str, symbol: str = "AAPL"):
    """Create a SCENARIO-seeded run. Should be excluded by REAL filter."""
    from datetime import date

    from db.models import NeutralRecommendation, ResearchRun, ResearchRunTicker

    as_of_date = date.fromisoformat(as_of_date_str)
    ts = datetime(as_of_date.year, as_of_date.month, as_of_date.day, 16, 0, 0, tzinfo=UTC)

    run_id = uuid.uuid4()
    run = ResearchRun(
        id=run_id,
        user_id=DEV_DEFAULT_USER_ID,
        run_type="MANUAL",
        status="COMPLETED",
        finished_at=ts,
        metadata_json={"scenario_seed": True, "scenario": "test_scenario"},
    )
    db_session.add(run)
    await db_session.flush()

    ticker = ResearchRunTicker(research_run_id=run_id, symbol=symbol, status="COMPLETED")
    db_session.add(ticker)
    await db_session.flush()

    nr = NeutralRecommendation(
        research_run_id=run_id,
        research_run_ticker_id=ticker.id,
        symbol=symbol,
        action="BUY_CANDIDATE",
        score=75,
        confidence=0.8,
        as_of_time=ts,
        created_at=ts,
        score_breakdown_json={},
        what_changed_json=[],
        main_reasons_json=[],
        main_risks_json=[],
        missing_details_json=[],
        final_reason="scenario",
        data_quality_score=0.9,
    )
    db_session.add(nr)
    await db_session.flush()
    return run, nr


# ── Integration tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replay_run_included_in_real_backtest(db_session):
    """REAL backtest includes historical replay recommendations inside date window."""
    import datetime as dt

    from backtesting.advisor_simulation import run_advisor_backtest

    await _seed_replay_rec(db_session, as_of_date_str="2026-01-15", symbol="AAPL")

    run = await run_advisor_backtest(
        session=db_session,
        user_id=DEV_DEFAULT_USER_ID,
        start_date=dt.date(2026, 1, 1),
        end_date=dt.date(2026, 2, 1),
        initial_cash=10_000,
        recommendation_source="REAL",
    )

    assert run is not None
    assert run.summary_json["recommendations_considered"] >= 1
    assert run.summary_json["recommendation_source"] == "REAL"


@pytest.mark.asyncio
async def test_scenario_run_excluded_from_real_backtest(db_session):
    """REAL backtest excludes scenario-seeded recommendations."""
    import datetime as dt

    from backtesting.advisor_simulation import run_advisor_backtest

    await _seed_scenario_rec(db_session, as_of_date_str="2026-01-15", symbol="AAPL")

    run = await run_advisor_backtest(
        session=db_session,
        user_id=DEV_DEFAULT_USER_ID,
        start_date=dt.date(2026, 1, 1),
        end_date=dt.date(2026, 2, 1),
        initial_cash=10_000,
        recommendation_source="REAL",
    )

    assert run.summary_json["recommendations_considered"] == 0


@pytest.mark.asyncio
async def test_replay_run_outside_window_excluded(db_session):
    """Replay run outside the backtest date window is excluded."""
    import datetime as dt

    from backtesting.advisor_simulation import run_advisor_backtest

    # as_of_date is in March — outside Jan–Feb window
    await _seed_replay_rec(db_session, as_of_date_str="2026-03-01", symbol="AAPL")

    run = await run_advisor_backtest(
        session=db_session,
        user_id=DEV_DEFAULT_USER_ID,
        start_date=dt.date(2026, 1, 1),
        end_date=dt.date(2026, 2, 1),
        initial_cash=10_000,
        recommendation_source="REAL",
    )

    assert run.summary_json["recommendations_considered"] == 0


@pytest.mark.asyncio
async def test_all_source_includes_both_replay_and_scenario(db_session):
    """ALL source includes both replay and scenario recommendations."""
    import datetime as dt

    from backtesting.advisor_simulation import run_advisor_backtest

    await _seed_replay_rec(db_session, as_of_date_str="2026-01-15", symbol="AAPL")
    await _seed_scenario_rec(db_session, as_of_date_str="2026-01-20", symbol="NVDA")

    run = await run_advisor_backtest(
        session=db_session,
        user_id=DEV_DEFAULT_USER_ID,
        start_date=dt.date(2026, 1, 1),
        end_date=dt.date(2026, 2, 1),
        initial_cash=10_000,
        recommendation_source="ALL",
    )

    assert run.summary_json["recommendations_considered"] >= 2
