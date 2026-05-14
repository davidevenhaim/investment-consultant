"""Tests for apps/cli/seed_advisor_scenario.py (M11.2)."""

from __future__ import annotations

import dataclasses
import datetime as dt
import uuid

import pytest

from apps.cli.seed_advisor_scenario import (
    _ACTION_ATTRS,
    DEFAULT_SCENARIO,
    DEV_DEFAULT_USER_ID,
    SCENARIOS,
    ScenarioRec,
    _score_breakdown,
    reset_scenario_for_user,
    seed_scenario,
    warn_non_scenario_recommendations_in_window,
)

TYPE_CHECKING = False
if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

# ── Pure unit tests (no DB) ───────────────────────────────────────────────────


def test_all_three_scenarios_defined() -> None:
    for name in ("mixed_buy_reduce_sell", "bullish_rotation", "risk_off"):
        assert name in SCENARIOS, f"Scenario '{name}' missing"
        assert len(SCENARIOS[name]) >= 2, f"Scenario '{name}' has too few recs"


def test_default_scenario_is_mixed() -> None:
    assert DEFAULT_SCENARIO == "mixed_buy_reduce_sell"


def test_mixed_buy_reduce_sell_has_required_actions() -> None:
    recs = SCENARIOS["mixed_buy_reduce_sell"]
    actions = {r.action for r in recs}
    buy_like = actions & {"BUY", "BUY_CANDIDATE", "STRONG_BUY"}
    assert buy_like, "mixed_buy_reduce_sell must have at least one BUY-like action"
    assert "REDUCE" in actions, "mixed_buy_reduce_sell must have REDUCE"
    assert "SELL" in actions, "mixed_buy_reduce_sell must have SELL"


def test_scores_in_valid_range() -> None:
    for recs in SCENARIOS.values():
        for rec in recs:
            score, conf = _ACTION_ATTRS.get(rec.action, (50, 0.60))
            assert 0 <= score <= 100, f"Score out of range for action={rec.action}"
            assert 0.0 <= conf <= 1.0, f"Confidence out of range for action={rec.action}"


def test_all_scenario_recs_have_future_ish_dates() -> None:
    for recs in SCENARIOS.values():
        for rec in recs:
            assert isinstance(rec.date, dt.date)
            assert rec.date.year >= 2026


def test_score_breakdown_includes_scenario_metadata() -> None:
    bd = _score_breakdown(72, "mixed_buy_reduce_sell")
    assert bd["scenario"] == "mixed_buy_reduce_sell"
    assert bd["scenario_seed"] is True
    assert bd["total"] == 72
    assert "components" in bd


def test_score_breakdown_components_are_non_negative() -> None:
    for score in (20, 50, 72, 88):
        bd = _score_breakdown(score, "test")
        for v in bd["components"].values():
            assert v >= 0


def test_dev_default_user_id_matches_auth_module() -> None:
    from apps.api.dependencies.auth import DEV_DEFAULT_USER_ID as AUTH_DEFAULT
    assert DEV_DEFAULT_USER_ID == AUTH_DEFAULT


def test_scenario_rec_is_frozen_dataclass() -> None:
    rec = ScenarioRec(dt.date(2026, 1, 1), "AAPL", "BUY")
    with pytest.raises(dataclasses.FrozenInstanceError):
        rec.symbol = "NVDA"  # type: ignore[misc]


# ── DB tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_seed_inserts_expected_row_count(db_session: AsyncSession) -> None:
    """seed_scenario inserts one NeutralRecommendation per ScenarioRec."""
    user_id = uuid.UUID("aaaaaaaa-1111-0000-0000-000000000001")
    created = await seed_scenario(db_session, user_id, "mixed_buy_reduce_sell")
    assert len(created) == len(SCENARIOS["mixed_buy_reduce_sell"])


@pytest.mark.asyncio
async def test_seed_rows_pass_db_constraints(db_session: AsyncSession) -> None:
    """All seeded rows satisfy score/confidence/as_of_time DB constraints."""
    from db.models import NeutralRecommendation
    from sqlalchemy import select

    user_id = uuid.UUID("aaaaaaaa-1111-0000-0000-000000000002")
    await seed_scenario(db_session, user_id, "mixed_buy_reduce_sell")

    result = await db_session.execute(
        select(NeutralRecommendation).where(
            NeutralRecommendation.symbol.in_(["AAPL", "NVDA", "AMD"])
        )
    )
    rows = result.scalars().all()
    assert len(rows) > 0
    for row in rows:
        assert row.as_of_time is not None
        assert 0 <= row.score <= 100
        assert 0.0 <= row.confidence <= 1.0
        assert row.score_breakdown_json.get("scenario_seed") is True


@pytest.mark.asyncio
async def test_seed_created_at_matches_rec_date(db_session: AsyncSession) -> None:
    """created_at on each NeutralRecommendation reflects the scenario rec date."""
    user_id = uuid.UUID("aaaaaaaa-1111-0000-0000-000000000003")
    created = await seed_scenario(db_session, user_id, "mixed_buy_reduce_sell")

    recs = SCENARIOS["mixed_buy_reduce_sell"]
    for nr, scenario_rec in zip(created, recs, strict=True):
        assert nr.created_at.date() == scenario_rec.date


@pytest.mark.asyncio
async def test_reset_removes_previous_rows(db_session: AsyncSession) -> None:
    """reset_scenario_for_user deletes seeded rows and allows re-seeding."""
    user_id = uuid.UUID("bbbbbbbb-2222-0000-0000-000000000001")

    first = await seed_scenario(db_session, user_id, "mixed_buy_reduce_sell")
    assert len(first) > 0

    n_deleted = await reset_scenario_for_user(db_session, user_id, "mixed_buy_reduce_sell")
    assert n_deleted == len(first)

    second = await seed_scenario(db_session, user_id, "mixed_buy_reduce_sell")
    assert len(second) == len(first)


@pytest.mark.asyncio
async def test_reset_does_not_affect_other_scenarios(db_session: AsyncSession) -> None:
    """Resetting mixed_buy_reduce_sell leaves bullish_rotation rows intact."""
    user_id = uuid.UUID("cccccccc-3333-0000-0000-000000000001")

    await seed_scenario(db_session, user_id, "mixed_buy_reduce_sell")
    bullish = await seed_scenario(db_session, user_id, "bullish_rotation")

    n_deleted = await reset_scenario_for_user(db_session, user_id, "mixed_buy_reduce_sell")
    assert n_deleted == len(SCENARIOS["mixed_buy_reduce_sell"])

    # Verify bullish_rotation recs still exist via run_ids
    from db.models import NeutralRecommendation
    from sqlalchemy import select
    bullish_ids = [nr.id for nr in bullish]
    result = await db_session.execute(
        select(NeutralRecommendation).where(NeutralRecommendation.id.in_(bullish_ids))
    )
    remaining = result.scalars().all()
    assert len(remaining) == len(bullish)


@pytest.mark.asyncio
async def test_reset_noop_when_no_rows(db_session: AsyncSession) -> None:
    """reset_scenario_for_user returns 0 when no matching rows exist."""
    user_id = uuid.UUID("dddddddd-4444-0000-0000-000000000001")
    n = await reset_scenario_for_user(db_session, user_id, "mixed_buy_reduce_sell")
    assert n == 0


@pytest.mark.asyncio
async def test_warn_non_scenario_overlap_emits_stderr(
    db_session: AsyncSession, capsys: pytest.CaptureFixture[str]
) -> None:
    """Overlapping non-seeded recs for scenario symbols/date window trigger WARNING."""
    from db.enums import ResearchRunStatus, ResearchRunType
    from db.models import NeutralRecommendation, ResearchRun

    user_id = uuid.UUID("99999999-aaaa-bbbb-cccc-000000000099")
    overlap = dt.date(2026, 2, 15)
    run = ResearchRun(
        user_id=user_id,
        run_type=ResearchRunType.MANUAL.value,
        status=ResearchRunStatus.COMPLETED.value,
        started_at=dt.datetime.combine(overlap, dt.time(9, 0), tzinfo=dt.UTC),
        finished_at=dt.datetime.combine(overlap, dt.time(10, 0), tzinfo=dt.UTC),
        metadata_json={},
    )
    db_session.add(run)
    await db_session.flush()

    rec_dt = dt.datetime.combine(overlap, dt.time(10, 0), tzinfo=dt.UTC)
    nr = NeutralRecommendation(
        research_run_id=run.id,
        symbol="AAPL",
        action="HOLD",
        score=55,
        confidence=0.65,
        final_reason="external",
        score_breakdown_json={},
        main_reasons_json=[],
        main_risks_json=[],
        missing_details_json=[],
        what_changed_json=[],
        as_of_time=rec_dt,
        price_at_recommendation=100.0,
    )
    nr.created_at = rec_dt
    db_session.add(nr)
    await db_session.flush()

    warned = await warn_non_scenario_recommendations_in_window(
        db_session, user_id, "mixed_buy_reduce_sell"
    )
    assert warned is True
    err = capsys.readouterr().err
    assert "WARNING" in err
    assert "mixed_buy_reduce_sell" in err


@pytest.mark.asyncio
async def test_warn_skips_when_only_seeded_rows(db_session: AsyncSession) -> None:
    user_id = uuid.UUID("aaaaaaaa-1111-0000-0000-000000000099")
    await seed_scenario(db_session, user_id, "mixed_buy_reduce_sell")
    assert (
        await warn_non_scenario_recommendations_in_window(
            db_session, user_id, "mixed_buy_reduce_sell"
        )
    ) is False


@pytest.mark.asyncio
async def test_seed_does_not_affect_other_users(db_session: AsyncSession) -> None:
    """Seeding for user A does not create rows visible to user B."""
    user_a = uuid.UUID("eeeeeeee-5555-0000-0000-000000000001")
    user_b = uuid.UUID("ffffffff-6666-0000-0000-000000000001")

    await seed_scenario(db_session, user_a, "risk_off")

    n_deleted = await reset_scenario_for_user(db_session, user_b, "risk_off")
    assert n_deleted == 0
