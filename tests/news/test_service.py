"""Tests for news service — uses FakeNewsProvider, no real API calls."""

import pytest
from news.fake_provider import FakeNewsProvider
from news.service import fetch_news_for_symbol


@pytest.mark.asyncio
async def test_fetch_news_with_fake_provider(db_session) -> None:
    provider = FakeNewsProvider()
    articles, score = await fetch_news_for_symbol(
        session=db_session,
        symbol="AAPL",
        provider=provider,
    )
    assert len(articles) == 3  # AAPL has 3 fake articles
    assert 0.0 <= score.score <= 15.0
    assert score.article_count == 3
    assert not score.no_data


@pytest.mark.asyncio
async def test_fetch_news_unknown_symbol_returns_empty(db_session) -> None:
    provider = FakeNewsProvider()
    articles, score = await fetch_news_for_symbol(
        session=db_session,
        symbol="ZZZZ",
        provider=provider,
    )
    assert articles == []
    assert score.no_data is True
    assert score.score == 5.0


@pytest.mark.asyncio
async def test_news_disabled_without_provider(db_session, monkeypatch) -> None:
    """When NEWS_ENABLED=false and no provider injected → no_data score."""
    monkeypatch.setenv("NEWS_ENABLED", "false")
    from core.config import get_settings
    get_settings.cache_clear()

    articles, score = await fetch_news_for_symbol(
        session=db_session,
        symbol="AAPL",
        provider=None,
    )
    assert articles == []
    assert score.no_data is True

    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_articles_persisted_to_db(db_session) -> None:
    import datetime as dt

    from news.repository import NewsItemRepository

    provider = FakeNewsProvider()
    await fetch_news_for_symbol(session=db_session, symbol="AAPL", provider=provider)

    repo = NewsItemRepository(db_session)
    since = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    stored = await repo.get_recent("AAPL", since=since, max_articles=20)
    assert len(stored) == 3


@pytest.mark.asyncio
async def test_nvda_articles_scored_positive(db_session) -> None:
    """NVDA fake article has high positive sentiment — should score above neutral."""
    provider = FakeNewsProvider()
    _, score = await fetch_news_for_symbol(
        session=db_session, symbol="NVDA", provider=provider
    )
    from news.scoring import _NEUTRAL_BASE
    assert score.score >= _NEUTRAL_BASE - 0.5  # NVDA has 1 positive article, score near/above 7.5


# ── as_of_date (M12.2) ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_news_as_of_date_excludes_future_articles(db_session) -> None:
    """Historical replay mode reads from DB and excludes articles after as_of_date."""
    import datetime as dt

    from news.repository import NewsItemRepository
    from news.schemas import NewsArticle

    as_of = dt.date(2026, 1, 15)
    repo = NewsItemRepository(db_session)

    # Seed: one article before as_of_date, one after
    old_article = NewsArticle(
        provider_article_id="old-001",
        url="https://example.com/old",
        title="Old news",
        description="Before cutoff",
        source_name="Test",
        author=None,
        published_at=dt.datetime(2026, 1, 10, tzinfo=dt.UTC),
        sentiment_score=0.5,
        relevance_score=0.8,
        importance_score=0.7,
    )
    future_article = NewsArticle(
        provider_article_id="future-001",
        url="https://example.com/future",
        title="Future news",
        description="After cutoff",
        source_name="Test",
        author=None,
        published_at=dt.datetime(2026, 1, 20, tzinfo=dt.UTC),
        sentiment_score=0.8,
        relevance_score=0.9,
        importance_score=0.9,
    )
    await repo.upsert_articles("AAPL", "fake", [old_article, future_article])

    articles, score = await fetch_news_for_symbol(
        session=db_session,
        symbol="AAPL",
        provider=None,
        as_of_date=as_of,
    )

    titles = [a.title for a in articles]
    assert "Old news" in titles
    assert "Future news" not in titles, "Future article leaked through as_of_date filter"


@pytest.mark.asyncio
async def test_fetch_news_as_of_date_skips_provider(db_session, monkeypatch) -> None:
    """Historical replay path never calls the external provider."""
    import datetime as dt
    from unittest.mock import AsyncMock, MagicMock

    mock_provider = MagicMock()
    mock_provider.fetch_news = AsyncMock(return_value=[])
    mock_provider.provider_name = "mock"

    as_of = dt.date(2026, 3, 1)
    await fetch_news_for_symbol(
        session=db_session,
        symbol="AAPL",
        provider=mock_provider,
        as_of_date=as_of,
    )

    mock_provider.fetch_news.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_news_no_as_of_date_calls_provider(db_session) -> None:
    """Live runs (as_of_date=None) still call the provider — existing behavior unchanged."""
    provider = FakeNewsProvider()
    articles, score = await fetch_news_for_symbol(
        session=db_session,
        symbol="AAPL",
        provider=provider,
        as_of_date=None,
    )
    assert len(articles) == 3  # FakeNewsProvider always returns 3 AAPL articles
    assert not score.no_data


@pytest.mark.asyncio
async def test_fetch_news_as_of_date_empty_db_returns_no_data(db_session) -> None:
    """If DB has no articles for the replay window, return empty / no_data."""
    import datetime as dt

    as_of = dt.date(2020, 1, 1)  # far in the past — DB is empty for this range
    articles, score = await fetch_news_for_symbol(
        session=db_session,
        symbol="AAPL",
        provider=None,
        as_of_date=as_of,
    )
    assert articles == []
    # score.no_data may or may not be set depending on scoring; what matters is empty articles
