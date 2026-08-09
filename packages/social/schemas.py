"""Pydantic schemas for the social package."""

import datetime as dt

from pydantic import BaseModel, Field


class SocialPostData(BaseModel):
    """A single social post from a provider (StockTwits message, tweet, ...)."""

    provider_post_id: str
    author_handle: str
    body: str
    url: str | None = None
    posted_at: dt.datetime
    sentiment_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    likes_count: int = Field(default=0, ge=0)
    reposts_count: int = Field(default=0, ge=0)
    replies_count: int | None = None
    is_duplicate: bool = False


class SocialScoreResult(BaseModel):
    """Output of deterministic social sentiment scoring (0–15)."""

    score: float = Field(ge=0.0, le=15.0)
    post_count: int = 0
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    positive_cap_applied: bool = False
    no_data: bool = False
    reason: str = ""
    top_posts: list[SocialPostData] = []
