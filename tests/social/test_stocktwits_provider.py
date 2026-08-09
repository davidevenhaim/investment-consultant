"""Tests for the StockTwits provider — httpx.MockTransport, no live calls."""

import datetime as dt
import json

import httpx
import pytest
from social.provider_stocktwits import StockTwitsProvider, _parse_message

_NOW = dt.datetime.now(dt.UTC)


def _message(
    message_id: int = 1,
    body: str = "$AAPL looking strong",
    sentiment: str | None = "Bullish",
    created_at: dt.datetime | None = None,
    likes: int = 3,
    reshares: int = 1,
) -> dict:
    created = created_at or (_NOW - dt.timedelta(hours=6))
    entities: dict = {"sentiment": {"basic": sentiment} if sentiment else None}
    return {
        "id": message_id,
        "body": body,
        "created_at": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "user": {"username": "twituser"},
        "entities": entities,
        "likes": {"total": likes},
        "reshares": {"reshared_count": reshares},
    }


def _provider_with_payload(payload: dict, status_code: int = 200) -> StockTwitsProvider:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, content=json.dumps(payload))

    return StockTwitsProvider(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_fetch_posts_maps_fields() -> None:
    provider = _provider_with_payload({"messages": [_message()]})
    posts = await provider.fetch_posts("AAPL")

    assert len(posts) == 1
    post = posts[0]
    assert post.provider_post_id == "1"
    assert post.author_handle == "twituser"
    assert post.sentiment_score == pytest.approx(0.6)
    assert post.likes_count == 3
    assert post.reposts_count == 1


@pytest.mark.asyncio
async def test_sentiment_mapping_bearish_and_none() -> None:
    payload = {
        "messages": [
            _message(message_id=1, sentiment="Bearish"),
            _message(message_id=2, sentiment=None),
        ]
    }
    posts = await _provider_with_payload(payload).fetch_posts("AAPL")
    by_id = {p.provider_post_id: p for p in posts}
    assert by_id["1"].sentiment_score == pytest.approx(-0.6)
    assert by_id["2"].sentiment_score == 0.0


@pytest.mark.asyncio
async def test_old_posts_filtered_by_day_window() -> None:
    payload = {
        "messages": [
            _message(message_id=1, created_at=_NOW - dt.timedelta(days=1)),
            _message(message_id=2, created_at=_NOW - dt.timedelta(days=30)),
        ]
    }
    posts = await _provider_with_payload(payload).fetch_posts("AAPL", days=7)
    assert [p.provider_post_id for p in posts] == ["1"]


@pytest.mark.asyncio
async def test_max_posts_cap() -> None:
    payload = {"messages": [_message(message_id=i) for i in range(10)]}
    posts = await _provider_with_payload(payload).fetch_posts("AAPL", max_posts=4)
    assert len(posts) == 4


@pytest.mark.asyncio
async def test_http_error_raises() -> None:
    provider = _provider_with_payload({}, status_code=429)
    with pytest.raises(httpx.HTTPStatusError):
        await provider.fetch_posts("AAPL")


def test_parse_message_malformed_returns_none() -> None:
    assert _parse_message({}) is None
    assert _parse_message({"id": 1, "body": ""}) is None
    assert _parse_message({"id": 1, "body": "x", "created_at": "not-a-date"}) is None
