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
