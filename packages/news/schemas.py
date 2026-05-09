"""Pydantic schemas for the news package."""

import datetime as dt

from pydantic import BaseModel, Field


class NewsArticle(BaseModel):
    """A single news article from a provider."""

    provider_article_id: str
    url: str
    title: str
    description: str | None = None
    source_name: str
    author: str | None = None
    published_at: dt.datetime
    sentiment_score: float = Field(default=0.0, ge=-1.0, le=1.0)
    relevance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    importance_score: float = Field(default=0.5, ge=0.0, le=1.0)
    is_duplicate: bool = False


class NewsScoreResult(BaseModel):
    """Output of deterministic news scoring (0–15)."""

    score: float = Field(ge=0.0, le=15.0)
    article_count: int = 0
    positive_count: int = 0
    negative_count: int = 0
    neutral_count: int = 0
    positive_cap_applied: bool = False
    no_data: bool = False
    reason: str = ""
    top_articles: list[NewsArticle] = []
