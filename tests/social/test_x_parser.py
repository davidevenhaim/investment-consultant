"""Tests for the pure X timeline parser — HTML fixtures, no browser."""

import datetime as dt

from social.provider_x import (
    _parse_count,
    extract_cashtags,
    parse_timeline_html,
    recent_only,
)
from social.schemas import SocialPostData

_TWEET_HTML = """
<html><body>
<article data-testid="tweet">
  <a href="/traderjoe/status/1234567890"><time datetime="2026-08-05T14:30:00.000Z">Aug 5</time></a>
  <div data-testid="tweetText"><span>$AAPL breaking out, </span><span>watching $NVDA too</span></div>
  <div data-testid="reply" aria-label="12 Replies"></div>
  <div data-testid="retweet" aria-label="1,234 reposts"></div>
  <div data-testid="like" aria-label="5.6K Likes"></div>
</article>
<article data-testid="tweet">
  <a href="/traderjoe/status/9999999999"><time datetime="2026-08-04T10:00:00.000Z">Aug 4</time></a>
  <div data-testid="tweetText"><span>no cashtags here, just vibes</span></div>
</article>
<article data-testid="tweet">
  <div data-testid="tweetText"><span>malformed tweet without permalink or time</span></div>
</article>
</body></html>
"""


def test_parse_timeline_extracts_tweets() -> None:
    posts = parse_timeline_html(_TWEET_HTML, handle="traderjoe")
    assert len(posts) == 2  # malformed third tweet skipped
    first = posts[0]
    assert first.provider_post_id == "1234567890"
    assert first.author_handle == "traderjoe"
    assert "$AAPL breaking out" in first.body
    assert first.url == "https://x.com/traderjoe/status/1234567890"
    assert first.posted_at == dt.datetime(2026, 8, 5, 14, 30, tzinfo=dt.UTC)
    assert first.replies_count == 12
    assert first.reposts_count == 1234
    assert first.likes_count == 5600
    assert first.sentiment_score == 0.0  # X posts carry no tagged sentiment


def test_parse_timeline_empty_html() -> None:
    assert parse_timeline_html("", handle="x") == []
    assert parse_timeline_html("<html><body>nothing</body></html>", handle="x") == []


def test_extract_cashtags() -> None:
    tags = extract_cashtags("$AAPL breaking out, watching $nvda and $TSLA. Not$FAKE $5")
    assert "AAPL" in tags
    assert "NVDA" in tags
    assert "TSLA" in tags
    assert "5" not in tags


def test_parse_count_formats() -> None:
    assert _parse_count("1,234") == 1234
    assert _parse_count("5.6K") == 5600
    assert _parse_count("1.2M") == 1_200_000
    assert _parse_count("") == 0
    assert _parse_count("garbage") == 0


def test_recent_only_filters_old_posts() -> None:
    now = dt.datetime(2026, 8, 7, tzinfo=dt.UTC)

    def post(post_id: str, days_ago: int) -> SocialPostData:
        return SocialPostData(
            provider_post_id=post_id,
            author_handle="a",
            body="b",
            posted_at=now - dt.timedelta(days=days_ago),
        )

    posts = [post("new", 2), post("old", 30)]
    kept = recent_only(posts, days=7, now=now)
    assert [p.provider_post_id for p in kept] == ["new"]
