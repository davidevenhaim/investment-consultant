"""Deterministic social sentiment scoring — 0 to 15 points.

Algorithm:
  - No posts → 5.0 (conservative: no boost, no penalty)
  - With posts → base 7.5 + per-post contributions
  - Per-post contribution = sentiment × engagement_weight, capped +1.5 / -1.25
    (posts are noisier than news articles, so caps are tighter)
  - engagement_weight = min(1.0, 0.3 + 0.1 * log10(1 + likes + 2*reposts))
  - Positive cap: 10.0 unless ≥5 independent positive posts → 12.5
"""

import math

from social.schemas import SocialPostData, SocialScoreResult

_NO_DATA_SCORE: float = 5.0
_NEUTRAL_BASE: float = 7.5
_MAX_POSITIVE_PER_POST: float = 1.5
_MAX_NEGATIVE_PER_POST: float = -1.25
_CAP_FEW_POSITIVE: float = 10.0
_CAP_MANY_POSITIVE: float = 12.5
_MANY_POSITIVE_COUNT: int = 5
_POSITIVE_THRESHOLD: float = 0.1
_NEGATIVE_THRESHOLD: float = -0.1
_ENGAGEMENT_BASE: float = 0.3
_ENGAGEMENT_LOG_FACTOR: float = 0.1
_REPOST_WEIGHT: int = 2


def _engagement_weight(post: SocialPostData) -> float:
    """0.3 (no engagement) up to 1.0; log-scaled so viral posts don't dominate."""
    engagement = post.likes_count + _REPOST_WEIGHT * post.reposts_count
    return min(1.0, _ENGAGEMENT_BASE + _ENGAGEMENT_LOG_FACTOR * math.log10(1 + engagement))


def _post_contribution(post: SocialPostData) -> float:
    """Contribution of a single post. Capped at +1.5 / -1.25."""
    combined = post.sentiment_score * _engagement_weight(post)
    if combined >= 0.0:
        return min(_MAX_POSITIVE_PER_POST, combined * _MAX_POSITIVE_PER_POST)
    return max(_MAX_NEGATIVE_PER_POST, combined * abs(_MAX_NEGATIVE_PER_POST))


def score_social_posts(posts: list[SocialPostData]) -> SocialScoreResult:
    """Score a list of social posts deterministically."""
    if not posts:
        return SocialScoreResult(
            score=_NO_DATA_SCORE,
            no_data=True,
            reason="No social data available. Conservative stub score applied.",
        )

    positive = [p for p in posts if p.sentiment_score > _POSITIVE_THRESHOLD]
    negative = [p for p in posts if p.sentiment_score < _NEGATIVE_THRESHOLD]
    neutral_count = len(posts) - len(positive) - len(negative)

    total_contribution = sum(_post_contribution(p) for p in posts)
    raw = _NEUTRAL_BASE + total_contribution

    cap_applied = False
    if raw > _CAP_FEW_POSITIVE:
        cap_applied = True
        raw = (
            min(raw, _CAP_MANY_POSITIVE)
            if len(positive) >= _MANY_POSITIVE_COUNT
            else _CAP_FEW_POSITIVE
        )

    score = round(max(0.0, min(15.0, raw)), 2)

    parts: list[str] = [f"{len(posts)} post(s) analyzed."]
    if positive:
        parts.append(f"{len(positive)} positive.")
    if negative:
        parts.append(f"{len(negative)} negative.")
    if cap_applied:
        parts.append("Positive cap applied (insufficient independent signals).")

    top = sorted(posts, key=lambda p: abs(_post_contribution(p)), reverse=True)[:5]

    return SocialScoreResult(
        score=score,
        post_count=len(posts),
        positive_count=len(positive),
        negative_count=len(negative),
        neutral_count=neutral_count,
        positive_cap_applied=cap_applied,
        no_data=False,
        reason=" ".join(parts),
        top_posts=top,
    )
