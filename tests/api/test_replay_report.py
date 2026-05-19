"""Tests for GET /api/v1/research-runs/historical-replay/{id}/report — M12.7."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from apps.api.dependencies.auth import DEV_DEFAULT_USER_ID

# ── Seed helpers ──────────────────────────────────────────────────────────────


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


async def _seed_neutral_rec(
    db_session: Any,
    *,
    run_id: uuid.UUID,
    symbol: str = "AAPL",
    action: str = "HOLD",
    score: int = 55,
    score_breakdown: dict[str, Any] | None = None,
    missing_details: list[Any] | None = None,
    price: float = 185.0,
) -> Any:
    from db.models import NeutralRecommendation

    rec = NeutralRecommendation(
        research_run_id=run_id,
        symbol=symbol.upper(),
        action=action,
        score=score,
        confidence=0.8,
        score_breakdown_json=score_breakdown or {"technical": 14.0, "fundamental": 10.0},
        what_changed_json=[],
        main_reasons_json=[],
        main_risks_json=[],
        missing_details_json=missing_details or [],
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


# ── Tests ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_replay_report_unknown_batch_returns_404(api_client: Any) -> None:
    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{uuid.uuid4()}/report")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_replay_report_wrong_user_returns_404(api_client: Any, db_session: Any) -> None:
    batch_id = str(uuid.uuid4())
    other_user = uuid.uuid4()
    await _seed_replay_run(
        db_session, user_id=other_user, replay_batch_id=batch_id, as_of_date="2026-01-01"
    )
    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}/report")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_replay_report_no_completed_runs_returns_422(
    api_client: Any, db_session: Any
) -> None:
    batch_id = str(uuid.uuid4())
    await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-01",
        status="QUEUED",
    )
    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}/report")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_replay_report_happy_path_returns_200(api_client: Any, db_session: Any) -> None:
    batch_id = str(uuid.uuid4())
    run = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-01",
    )
    n = await _seed_neutral_rec(db_session, run_id=run.id)
    await _seed_personalized_rec(db_session, neutral_id=n.id)

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}/report")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["replay_batch_id"] == batch_id
    assert data["completed_run_count"] == 1
    assert "AAPL" in data["symbols"]
    assert data["first_as_of_date"] == "2026-01-01"
    assert data["last_as_of_date"] == "2026-01-01"
    assert len(data["timelines"]) == 1


@pytest.mark.asyncio
async def test_replay_report_only_uses_completed_runs(api_client: Any, db_session: Any) -> None:
    """QUEUED runs in the batch must not appear in the report."""
    batch_id = str(uuid.uuid4())
    completed_run = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-01",
        status="COMPLETED",
    )
    queued_run = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-08",
        status="QUEUED",
    )
    await _seed_neutral_rec(db_session, run_id=completed_run.id, score=50)
    # Seed a rec for queued run — must NOT appear
    await _seed_neutral_rec(db_session, run_id=queued_run.id, score=60)

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}/report")
    data = resp.json()["data"]
    assert data["completed_run_count"] == 1
    aapl_timeline = data["timelines"][0]
    assert len(aapl_timeline["points"]) == 1
    assert aapl_timeline["points"][0]["as_of_date"] == "2026-01-01"


@pytest.mark.asyncio
async def test_replay_report_groups_by_symbol(api_client: Any, db_session: Any) -> None:
    """Two symbols in the batch → two timeline entries."""
    batch_id = str(uuid.uuid4())
    run = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-01",
        symbols=["AAPL", "NVDA"],
    )
    await _seed_neutral_rec(db_session, run_id=run.id, symbol="AAPL", score=55)
    await _seed_neutral_rec(db_session, run_id=run.id, symbol="NVDA", score=70)

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}/report")
    data = resp.json()["data"]
    symbols = [t["symbol"] for t in data["timelines"]]
    assert "AAPL" in symbols
    assert "NVDA" in symbols
    assert len(data["timelines"]) == 2


@pytest.mark.asyncio
async def test_replay_report_points_ordered_by_as_of_date(api_client: Any, db_session: Any) -> None:
    """Points in each timeline are asc-ordered by as_of_date."""
    batch_id = str(uuid.uuid4())
    run1 = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-15",
    )
    run2 = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-01",
    )
    await _seed_neutral_rec(db_session, run_id=run1.id, score=55)
    await _seed_neutral_rec(db_session, run_id=run2.id, score=60)

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}/report")
    pts = resp.json()["data"]["timelines"][0]["points"]
    dates = [p["as_of_date"] for p in pts]
    assert dates == sorted(dates)
    assert dates[0] == "2026-01-01"


@pytest.mark.asyncio
async def test_replay_report_summary_fields(api_client: Any, db_session: Any) -> None:
    """Summary has first_action, last_action, score_change, min/max_score."""
    batch_id = str(uuid.uuid4())
    run1 = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-01",
    )
    run2 = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-08",
    )
    await _seed_neutral_rec(db_session, run_id=run1.id, action="HOLD", score=55)
    await _seed_neutral_rec(db_session, run_id=run2.id, action="BUY_CANDIDATE", score=72)

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}/report")
    summary = resp.json()["data"]["timelines"][0]["summary"]
    assert summary["first_action"] == "HOLD"
    assert summary["last_action"] == "BUY_CANDIDATE"
    assert summary["action_changed"] is True
    assert summary["score_change"] == 17  # 72 - 55
    assert summary["min_score"] == 55
    assert summary["max_score"] == 72
    assert summary["point_count"] == 2


@pytest.mark.asyncio
async def test_replay_report_changes_detect_score_delta(api_client: Any, db_session: Any) -> None:
    batch_id = str(uuid.uuid4())
    run1 = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-01",
    )
    run2 = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-08",
    )
    await _seed_neutral_rec(db_session, run_id=run1.id, score=60)
    await _seed_neutral_rec(db_session, run_id=run2.id, score=55)

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}/report")
    changes = resp.json()["data"]["timelines"][0]["changes"]
    assert len(changes) == 1
    assert changes[0]["neutral_score_delta"] == -5


@pytest.mark.asyncio
async def test_replay_report_changes_detect_action_change(api_client: Any, db_session: Any) -> None:
    batch_id = str(uuid.uuid4())
    run1 = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-01",
    )
    run2 = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-08",
    )
    await _seed_neutral_rec(db_session, run_id=run1.id, action="HOLD", score=55)
    await _seed_neutral_rec(db_session, run_id=run2.id, action="REDUCE", score=40)

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}/report")
    chg = resp.json()["data"]["timelines"][0]["changes"][0]
    assert chg["action_changed"] is True
    assert chg["neutral_action_from"] == "HOLD"
    assert chg["neutral_action_to"] == "REDUCE"


@pytest.mark.asyncio
async def test_replay_report_changed_components_detected(api_client: Any, db_session: Any) -> None:
    """changed_components lists numeric score_breakdown_json fields that moved."""
    batch_id = str(uuid.uuid4())
    run1 = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-01",
    )
    run2 = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-08",
    )
    await _seed_neutral_rec(
        db_session,
        run_id=run1.id,
        score=55,
        score_breakdown={"technical": 14.0, "fundamental": 10.0},
    )
    await _seed_neutral_rec(
        db_session,
        run_id=run2.id,
        score=52,
        score_breakdown={"technical": 11.0, "fundamental": 10.0},
    )

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}/report")
    comps = resp.json()["data"]["timelines"][0]["changes"][0]["changed_components"]
    assert len(comps) == 1
    assert comps[0]["key"] == "technical"
    assert comps[0]["delta"] == -3.0


@pytest.mark.asyncio
async def test_replay_report_explanation_is_non_empty(api_client: Any, db_session: Any) -> None:
    batch_id = str(uuid.uuid4())
    run1 = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-01",
    )
    run2 = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-08",
    )
    await _seed_neutral_rec(db_session, run_id=run1.id, score=55)
    await _seed_neutral_rec(db_session, run_id=run2.id, score=55)  # no change

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}/report")
    changes = resp.json()["data"]["timelines"][0]["changes"]
    assert len(changes) == 1
    assert len(changes[0]["explanation"]) > 0
    assert "stable" in changes[0]["explanation"].lower()


@pytest.mark.asyncio
async def test_replay_report_personalized_action_included(api_client: Any, db_session: Any) -> None:
    batch_id = str(uuid.uuid4())
    run = await _seed_replay_run(
        db_session,
        user_id=DEV_DEFAULT_USER_ID,
        replay_batch_id=batch_id,
        as_of_date="2026-01-01",
    )
    n = await _seed_neutral_rec(db_session, run_id=run.id, action="HOLD")
    await _seed_personalized_rec(db_session, neutral_id=n.id, personal_action="REDUCE")

    resp = await api_client.get(f"/api/v1/research-runs/historical-replay/{batch_id}/report")
    point = resp.json()["data"]["timelines"][0]["points"][0]
    assert point["neutral_action"] == "HOLD"
    assert point["personalized_action"] == "REDUCE"
