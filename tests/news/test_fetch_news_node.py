"""Tests for the fetch_news graph node."""

import datetime as dt
from typing import TYPE_CHECKING

import pytest
from news.fake_provider import FakeNewsProvider
from news.scoring import _NO_DATA_SCORE
from research_graph.nodes.fetch_news import make_fetch_news

if TYPE_CHECKING:
    from news.schemas import NewsScoreResult


def _make_state(symbol: str = "AAPL") -> dict:
    return {
        "symbol": symbol,
        "run_id": "00000000-0000-0000-0000-000000000001",
        "run_ticker_id": "00000000-0000-0000-0000-000000000002",
        "as_of_time": dt.datetime(2026, 5, 9, tzinfo=dt.UTC),
        "strategy_version": "v0.1.0",
        "prompt_version": "v0.1.0",
        "strategy_config": {},
        "news_items": [],
        "news_score_result": None,
        "errors": [],
        "confidence_penalties": [],
    }


@pytest.mark.asyncio
async def test_fetch_news_node_returns_score(db_session) -> None:
    provider = FakeNewsProvider()
    node = make_fetch_news(db_session, news_provider=provider)
    result = await node(_make_state("AAPL"))

    assert "news_items" in result
    assert "news_score_result" in result
    assert len(result["news_items"]) == 3
    score: NewsScoreResult = result["news_score_result"]
    assert 0.0 <= score.score <= 15.0
    assert not score.no_data


@pytest.mark.asyncio
async def test_fetch_news_node_unknown_symbol_no_data(db_session) -> None:
    provider = FakeNewsProvider()
    node = make_fetch_news(db_session, news_provider=provider)
    result = await node(_make_state("ZZZZ"))

    assert result["news_items"] == []
    score: NewsScoreResult = result["news_score_result"]
    assert score.no_data is True
    assert score.score == _NO_DATA_SCORE


@pytest.mark.asyncio
async def test_fetch_news_node_no_provider_no_errors(db_session, monkeypatch) -> None:
    """Without a provider and NEWS_ENABLED=false, node returns no_data without crashing."""
    monkeypatch.setenv("NEWS_ENABLED", "false")
    from core.config import get_settings

    get_settings.cache_clear()

    node = make_fetch_news(db_session, news_provider=None)
    result = await node(_make_state("AAPL"))

    assert result["news_score_result"].no_data is True
    assert "errors" not in result or not result.get("errors")

    get_settings.cache_clear()


# ── as_of_date (M12.2) ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_news_node_as_of_date_excludes_future_articles(db_session) -> None:
    """fetch_news node with as_of_date in state uses historical mode (DB-only, date-capped)."""
    from news.repository import NewsItemRepository
    from news.schemas import NewsArticle

    as_of_str = "2026-01-15"
    repo = NewsItemRepository(db_session)

    # Pre-seed: one article before cutoff, one after
    await repo.upsert_articles(
        "AAPL",
        "fake",
        [
            NewsArticle(
                provider_article_id="past-001",
                url="https://example.com/past",
                title="Past event",
                description=None,
                source_name="Test",
                author=None,
                published_at=dt.datetime(2026, 1, 10, tzinfo=dt.UTC),
                sentiment_score=0.4,
                relevance_score=0.7,
                importance_score=0.6,
            ),
            NewsArticle(
                provider_article_id="future-002",
                url="https://example.com/future2",
                title="Future leak",
                description=None,
                source_name="Test",
                author=None,
                published_at=dt.datetime(2026, 1, 20, tzinfo=dt.UTC),
                sentiment_score=0.9,
                relevance_score=0.9,
                importance_score=0.9,
            ),
        ],
    )

    state = {**_make_state("AAPL"), "as_of_date": as_of_str}
    node = make_fetch_news(db_session, news_provider=None)
    result = await node(state)

    titles = [item["title"] for item in result["news_items"]]
    assert "Past event" in titles
    assert "Future leak" not in titles, "Future article must not appear in replay mode"


@pytest.mark.asyncio
async def test_fetch_news_node_no_as_of_date_calls_provider(db_session) -> None:
    """Live run (no as_of_date) still delegates to provider — existing behavior unchanged."""
    provider = FakeNewsProvider()
    state = _make_state("AAPL")  # as_of_date absent
    node = make_fetch_news(db_session, news_provider=provider)
    result = await node(state)
    assert len(result["news_items"]) == 3  # FakeNewsProvider returns 3 AAPL articles
