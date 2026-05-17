"""Tests for persist_results node with historical replay as_of_date (M12.1).

Verifies that NeutralRecommendation.created_at and as_of_time are set to
as_of_date 16:00 UTC for replay runs, while normal runs use wall-clock time.
"""

import uuid
from datetime import UTC, datetime

import pytest

from apps.api.dependencies.auth import DEV_DEFAULT_USER_ID

# ── Helpers ────────────────────────────────────────────────────────────────────


def _make_state(*, as_of_date: str | None = None, symbol: str = "AAPL") -> dict:
    """Build a minimal ResearchState dict for persist_results tests."""
    from db.enums import RecommendationAction
    from research_graph.state import NeutralRecState, ScoreBreakdown

    neutral = NeutralRecState(
        action=RecommendationAction.HOLD,
        score=55,
        confidence=0.7,
        final_reason="test",
        score_breakdown=ScoreBreakdown(total_score=55),
    )

    return {
        "run_id": str(uuid.uuid4()),
        "run_ticker_id": str(uuid.uuid4()),
        "user_id": str(DEV_DEFAULT_USER_ID),
        "symbol": symbol,
        "as_of_time": datetime.now(UTC),
        "as_of_date": as_of_date,
        "strategy_version": "v0.1.0",
        "prompt_version": "v0.1.0",
        "strategy_config": {},
        "neutral_rec": neutral,
        "personalized_rec": None,
        "technical_signals": {"latest_close": 175.0},
        "llm_analysis": None,
        "news_score_result": None,
        "portfolio_context": None,
        "current_position_weight": 0.0,
        "target_position_weight": None,
        "cash_available": None,
        "suggested_trade_json": None,
        "errors": [],
    }


# ── DB-bound persist tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_persist_replay_sets_created_at_to_as_of_date(db_session):
    """NeutralRecommendation.created_at is as_of_date 16:00 UTC for replay runs."""
    from db.models import NeutralRecommendation, ResearchRun, ResearchRunTicker
    from research_graph.nodes.persist_results import make_persist_results

    # Seed run + ticker so FK constraints are satisfied
    run_id = uuid.uuid4()
    ticker_id = uuid.uuid4()
    run = ResearchRun(
        id=run_id,
        user_id=DEV_DEFAULT_USER_ID,
        run_type="HISTORICAL_REPLAY",
        status="RUNNING",
    )
    ticker = ResearchRunTicker(
        id=ticker_id,
        research_run_id=run_id,
        symbol="AAPL",
        status="RUNNING",
    )
    db_session.add_all([run, ticker])
    await db_session.flush()

    state = _make_state(as_of_date="2026-01-15")
    state["run_id"] = str(run_id)
    state["run_ticker_id"] = str(ticker_id)

    persist = make_persist_results(db_session, memory_store=None)
    await persist(state)  # type: ignore[arg-type]

    # Verify NeutralRecommendation.created_at
    from sqlalchemy import select

    result = await db_session.execute(
        select(NeutralRecommendation).where(NeutralRecommendation.research_run_id == run_id)
    )
    nr = result.scalar_one_or_none()
    assert nr is not None
    expected_ts = datetime(2026, 1, 15, 16, 0, 0, tzinfo=UTC)
    assert nr.created_at == expected_ts
    assert nr.as_of_time == expected_ts


@pytest.mark.asyncio
async def test_persist_normal_run_uses_wall_clock_created_at(db_session):
    """Normal (non-replay) run uses wall-clock time for NeutralRecommendation.created_at."""
    from db.models import NeutralRecommendation, ResearchRun, ResearchRunTicker
    from research_graph.nodes.persist_results import make_persist_results

    run_id = uuid.uuid4()
    ticker_id = uuid.uuid4()
    run = ResearchRun(
        id=run_id,
        user_id=DEV_DEFAULT_USER_ID,
        run_type="MANUAL",
        status="RUNNING",
    )
    ticker = ResearchRunTicker(
        id=ticker_id,
        research_run_id=run_id,
        symbol="NVDA",
        status="RUNNING",
    )
    db_session.add_all([run, ticker])
    await db_session.flush()

    state = _make_state(as_of_date=None, symbol="NVDA")
    state["run_id"] = str(run_id)
    state["run_ticker_id"] = str(ticker_id)

    persist = make_persist_results(db_session, memory_store=None)
    await persist(state)  # type: ignore[arg-type]

    from sqlalchemy import select

    result = await db_session.execute(
        select(NeutralRecommendation).where(NeutralRecommendation.research_run_id == run_id)
    )
    nr = result.scalar_one_or_none()
    assert nr is not None
    # created_at should be server-default (near now), not a historical date
    # NOTE: server_default=func.now() runs in DB; the Python object may have
    # created_at=None until refreshed. Check as_of_time instead which we control.
    assert nr.as_of_time is not None
    # as_of_time should be the state's as_of_time (wall-clock), not a 2026-01-15 date
    assert nr.as_of_time.year >= 2026
    # Should NOT be exactly 16:00:00 (which is the replay sentinel time)
    replay_sentinel = datetime(2026, 1, 15, 16, 0, 0, tzinfo=UTC)
    assert nr.as_of_time != replay_sentinel
