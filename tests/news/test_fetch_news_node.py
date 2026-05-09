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
