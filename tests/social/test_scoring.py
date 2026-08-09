"""Tests for deterministic social sentiment scoring logic."""

import datetime as dt

import pytest
from social.schemas import SocialPostData
from social.scoring import (
    _CAP_FEW_POSITIVE,
    _CAP_MANY_POSITIVE,
    _NEUTRAL_BASE,
    _NO_DATA_SCORE,
    _engagement_weight,
    score_social_posts,
)


def _post(
    sentiment: float = 0.0,
    likes: int = 0,
    reposts: int = 0,
    post_id: str = "p-001",
) -> SocialPostData:
    return SocialPostData(
        provider_post_id=post_id,
        author_handle="tester",
        body="test post",
        posted_at=dt.datetime(2026, 8, 1, tzinfo=dt.UTC),
        sentiment_score=sentiment,
        likes_count=likes,
        reposts_count=reposts,
    )


def test_no_posts_returns_stub_score() -> None:
    result = score_social_posts([])
    assert result.score == _NO_DATA_SCORE
    assert result.no_data is True
    assert result.post_count == 0


def test_neutral_posts_stay_at_base() -> None:
    posts = [_post(sentiment=0.0, post_id=f"n{i}") for i in range(3)]
    result = score_social_posts(posts)
    assert result.score == pytest.approx(_NEUTRAL_BASE, abs=0.01)
    assert result.no_data is False
    assert result.neutral_count == 3


def test_score_always_within_bounds() -> None:
    extreme_pos = [_post(sentiment=1.0, likes=100_000, post_id=f"p{i}") for i in range(20)]
    extreme_neg = [_post(sentiment=-1.0, likes=100_000, post_id=f"m{i}") for i in range(20)]
    assert 0.0 <= score_social_posts(extreme_pos).score <= 15.0
    assert 0.0 <= score_social_posts(extreme_neg).score <= 15.0


def test_few_positive_posts_capped_at_10() -> None:
    posts = [_post(sentiment=1.0, likes=10_000, post_id=f"p{i}") for i in range(3)]
    result = score_social_posts(posts)
    assert result.score == pytest.approx(_CAP_FEW_POSITIVE, abs=0.01)
    assert result.positive_cap_applied is True


def test_many_positive_posts_cap_raises_to_12_5() -> None:
    posts = [_post(sentiment=1.0, likes=10_000, post_id=f"p{i}") for i in range(6)]
    result = score_social_posts(posts)
    assert result.score == pytest.approx(_CAP_MANY_POSITIVE, abs=0.01)
    assert result.positive_cap_applied is True
    assert result.positive_count == 6


def test_negative_posts_lower_score_below_base() -> None:
    posts = [_post(sentiment=-0.8, likes=500, post_id=f"m{i}") for i in range(3)]
    result = score_social_posts(posts)
    assert result.score < _NEUTRAL_BASE
    assert result.negative_count == 3


def test_engagement_weight_deterministic_and_bounded() -> None:
    low = _engagement_weight(_post(likes=0, reposts=0))
    mid = _engagement_weight(_post(likes=50, reposts=10))
    high = _engagement_weight(_post(likes=100_000_000, reposts=0))
    assert low == pytest.approx(0.3, abs=0.001)
    assert low < mid < high
    assert high == 1.0  # cap reached at engagement >= 10^7
    # Same input → same output
    assert _engagement_weight(_post(likes=50, reposts=10)) == mid


def test_high_engagement_moves_score_more_than_low() -> None:
    viral = score_social_posts([_post(sentiment=0.6, likes=50_000)])
    quiet = score_social_posts([_post(sentiment=0.6, likes=0)])
    assert viral.score > quiet.score


def test_top_posts_limited_to_five() -> None:
    posts = [_post(sentiment=0.5, likes=i * 10, post_id=f"p{i}") for i in range(10)]
    result = score_social_posts(posts)
    assert len(result.top_posts) == 5
