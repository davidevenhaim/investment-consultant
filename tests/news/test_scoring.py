"""Tests for deterministic news scoring logic."""

import datetime as dt

import pytest
from news.schemas import NewsArticle
from news.scoring import _NEUTRAL_BASE, _NO_DATA_SCORE, score_news_articles


def _article(
    sentiment: float = 0.0,
    importance: float = 0.5,
    relevance: float = 0.5,
    article_id: str = "test-001",
) -> NewsArticle:
    return NewsArticle(
        provider_article_id=article_id,
        url=f"https://example.com/{article_id}",
        title="Test article",
        source_name="Test Source",
        published_at=dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
        sentiment_score=sentiment,
        importance_score=importance,
        relevance_score=relevance,
    )


def test_no_articles_returns_stub_score():
    result = score_news_articles([])
    assert result.score == _NO_DATA_SCORE
    assert result.no_data is True
    assert result.article_count == 0


def test_neutral_articles_near_base():
    articles = [_article(sentiment=0.0, article_id=f"n{i}") for i in range(3)]
    result = score_news_articles(articles)
    assert result.score == pytest.approx(_NEUTRAL_BASE, abs=1.0)
    assert result.no_data is False


def test_single_strong_positive_capped_at_10():
    """1 strong positive article → raw > 10 → capped at 10 (< 3 independent signals)."""
    articles = [_article(sentiment=1.0, importance=1.0, relevance=1.0)]
    result = score_news_articles(articles)
    assert result.score == pytest.approx(10.0, abs=0.01)
    assert result.positive_cap_applied is True
    assert result.positive_count == 1


def test_three_positive_articles_cap_raises_to_12_5():
    """≥3 independent positive signals → cap rises to 12.5."""
    articles = [
        _article(sentiment=1.0, importance=1.0, relevance=1.0, article_id=f"p{i}")
        for i in range(3)
    ]
    result = score_news_articles(articles)
    assert result.score == pytest.approx(12.5, abs=0.01)
    assert result.positive_cap_applied is True
    assert result.positive_count == 3


def test_negative_articles_lower_score():
    articles = [
        _article(sentiment=-1.0, importance=1.0, relevance=1.0, article_id=f"neg{i}")
        for i in range(3)
    ]
    result = score_news_articles(articles)
    assert result.score < _NEUTRAL_BASE
    assert result.negative_count == 3
    assert result.score >= 0.0


def test_strongly_negative_approaches_zero():
    """5 very negative articles should push score toward 0."""
    articles = [
        _article(sentiment=-1.0, importance=1.0, relevance=1.0, article_id=f"neg{i}")
        for i in range(5)
    ]
    result = score_news_articles(articles)
    assert result.score <= 2.0


def test_single_article_max_contribution_three():
    """No single article contributes more than 3.0 pts."""
    articles = [_article(sentiment=1.0, importance=1.0, relevance=1.0)]
    # raw = 7.5 + 3.0 = 10.5 → capped at 10
    result = score_news_articles(articles)
    assert result.score <= 10.0 + 0.01


def test_score_bounded_0_to_15():
    """Score always in [0, 15]."""
    for sentiment in [-1.0, -0.5, 0.0, 0.5, 1.0]:
        articles = [_article(sentiment=sentiment, article_id=f"s{int(sentiment*10)}")]
        result = score_news_articles(articles)
        assert 0.0 <= result.score <= 15.0


def test_top_articles_populated():
    articles = [_article(sentiment=0.8, article_id=f"a{i}") for i in range(6)]
    result = score_news_articles(articles)
    assert len(result.top_articles) <= 5


def test_mixed_positive_negative():
    articles = [
        _article(sentiment=0.8, importance=0.9, relevance=0.9, article_id="pos"),
        _article(sentiment=-0.6, importance=0.7, relevance=0.7, article_id="neg"),
    ]
    result = score_news_articles(articles)
    # Mixed: score should be near neutral base
    assert 5.0 <= result.score <= 12.0
    assert result.positive_count == 1
    assert result.negative_count == 1
