"""Tests for the fetch_social graph node."""

import datetime as dt
from typing import TYPE_CHECKING

import pytest
from research_graph.nodes.fetch_social import make_fetch_social
from social.fake_provider import FakeSocialProvider
from social.scoring import _NO_DATA_SCORE

if TYPE_CHECKING:
    from social.schemas import SocialScoreResult


def _make_state(symbol: str = "AAPL") -> dict:
    return {
        "symbol": symbol,
        "run_id": "00000000-0000-0000-0000-000000000001",
        "run_ticker_id": "00000000-0000-0000-0000-000000000002",
        "as_of_time": dt.datetime(2026, 8, 7, tzinfo=dt.UTC),
        "strategy_version": "v0.1.0",
        "prompt_version": "v0.1.0",
        "strategy_config": {},
        "social_posts": [],
        "social_score_result": None,
        "errors": [],
        "confidence_penalties": [],
    }


@pytest.mark.asyncio
async def test_fetch_social_node_returns_score(db_session) -> None:
    node = make_fetch_social(db_session, social_provider=FakeSocialProvider())
    result = await node(_make_state("AAPL"))

    assert len(result["social_posts"]) == 3
    score: SocialScoreResult = result["social_score_result"]
    assert 0.0 <= score.score <= 15.0
    assert not score.no_data


@pytest.mark.asyncio
async def test_fetch_social_node_unknown_symbol_no_data(db_session) -> None:
    node = make_fetch_social(db_session, social_provider=FakeSocialProvider())
    result = await node(_make_state("ZZZZ"))

    assert result["social_posts"] == []
    score: SocialScoreResult = result["social_score_result"]
    assert score.no_data is True
    assert score.score == _NO_DATA_SCORE


@pytest.mark.asyncio
async def test_fetch_social_node_disabled_no_errors(db_session) -> None:
    """Without a provider and SOCIAL_ENABLED=false, node returns no_data without crashing."""
    node = make_fetch_social(db_session, social_provider=None)
    result = await node(_make_state("AAPL"))

    assert result["social_score_result"].no_data is True
    assert "errors" not in result or not result.get("errors")


@pytest.mark.asyncio
async def test_fetch_social_node_as_of_date_excludes_future_posts(db_session) -> None:
    from social.repository import SocialPostRepository
    from social.schemas import SocialPostData

    repo = SocialPostRepository(db_session)
    await repo.upsert_posts(
        symbol="AAPL",
        provider="fake",
        posts=[
            SocialPostData(
                provider_post_id="node-past",
                author_handle="early",
                body="past post",
                posted_at=dt.datetime(2026, 1, 10, tzinfo=dt.UTC),
                sentiment_score=0.6,
            ),
            SocialPostData(
                provider_post_id="node-future",
                author_handle="leaker",
                body="future post",
                posted_at=dt.datetime(2026, 1, 20, tzinfo=dt.UTC),
                sentiment_score=0.6,
            ),
        ],
    )

    state = {**_make_state("AAPL"), "as_of_date": "2026-01-15"}
    node = make_fetch_social(db_session, social_provider=None)
    result = await node(state)

    ids = [p["provider_post_id"] for p in result["social_posts"]]
    assert "node-past" in ids
    assert "node-future" not in ids, "Future post must not appear in replay mode"
