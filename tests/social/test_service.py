"""Tests for the social ingestion service (fetch + persist + score)."""

import datetime as dt

import pytest
from social.fake_provider import FakeSocialProvider
from social.interfaces import SocialProvider
from social.repository import SocialPostRepository
from social.schemas import SocialPostData
from social.scoring import _NO_DATA_SCORE
from social.service import fetch_social_for_symbol


class _FailingProvider(SocialProvider):
    @property
    def provider_name(self) -> str:
        return "failing"

    async def fetch_posts(
        self, symbol: str, days: int = 7, max_posts: int = 30
    ) -> list[SocialPostData]:
        raise RuntimeError("provider down")


@pytest.mark.asyncio
async def test_live_fetch_scores_and_persists(db_session) -> None:
    posts, score = await fetch_social_for_symbol(
        db_session, "AAPL", provider=FakeSocialProvider()
    )

    assert len(posts) == 3
    assert score.no_data is False
    assert 0.0 <= score.score <= 15.0

    repo = SocialPostRepository(db_session)
    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=30)
    rows = await repo.get_recent("AAPL", since=since)
    assert len(rows) == 3
    assert all(r.provider == "fake" for r in rows)


@pytest.mark.asyncio
async def test_disabled_gate_returns_stub(db_session) -> None:
    # SOCIAL_ENABLED defaults to false in tests; no provider, no as_of_date → gate applies.
    posts, score = await fetch_social_for_symbol(db_session, "AAPL")
    assert posts == []
    assert score.no_data is True
    assert score.score == _NO_DATA_SCORE


@pytest.mark.asyncio
async def test_provider_failure_degrades_to_no_data(db_session) -> None:
    posts, score = await fetch_social_for_symbol(
        db_session, "MSFT", provider=_FailingProvider()
    )
    assert posts == []
    assert score.no_data is True
    assert score.score == _NO_DATA_SCORE


@pytest.mark.asyncio
async def test_live_merges_db_posts_from_other_providers(db_session) -> None:
    """Host-scraped X posts stored in the DB merge into the scored set."""
    repo = SocialPostRepository(db_session)
    await repo.upsert_posts(
        symbol="AAPL",
        provider="x",
        posts=[
            SocialPostData(
                provider_post_id="x-001",
                author_handle="xtrader",
                body="$AAPL to the moon",
                posted_at=dt.datetime.now(dt.UTC) - dt.timedelta(hours=3),
                sentiment_score=0.0,
                likes_count=10,
            )
        ],
    )

    posts, score = await fetch_social_for_symbol(
        db_session, "AAPL", provider=FakeSocialProvider()
    )
    handles = {p.author_handle for p in posts}
    assert "xtrader" in handles  # merged from DB
    assert "bullinvestor" in handles  # from live provider
    assert score.post_count == len(posts) == 4


@pytest.mark.asyncio
async def test_replay_as_of_date_caps_posts(db_session) -> None:
    """Replay mode is DB-only and must exclude posts after as_of_date."""
    repo = SocialPostRepository(db_session)
    as_of = dt.date(2026, 6, 15)
    await repo.upsert_posts(
        symbol="TSLA",
        provider="stocktwits",
        posts=[
            SocialPostData(
                provider_post_id="past-1",
                author_handle="early",
                body="past post",
                posted_at=dt.datetime(2026, 6, 12, tzinfo=dt.UTC),
                sentiment_score=0.6,
            ),
            SocialPostData(
                provider_post_id="future-1",
                author_handle="leaker",
                body="future post",
                posted_at=dt.datetime(2026, 6, 20, tzinfo=dt.UTC),
                sentiment_score=0.6,
            ),
        ],
    )

    posts, score = await fetch_social_for_symbol(db_session, "TSLA", as_of_date=as_of)
    ids = [p.provider_post_id for p in posts]
    assert "past-1" in ids
    assert "future-1" not in ids, "Future post must not leak into replay"
    assert score.no_data is False


@pytest.mark.asyncio
async def test_replay_before_ingestion_returns_stub(db_session) -> None:
    posts, score = await fetch_social_for_symbol(
        db_session, "NVDA", as_of_date=dt.date(2020, 1, 1)
    )
    assert posts == []
    assert score.no_data is True
    assert score.score == _NO_DATA_SCORE
