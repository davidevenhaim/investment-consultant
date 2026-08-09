"""X (Twitter) timeline scraper — host-only, Playwright, logged-in session.

Operational constraints (see CLAUDE.md safety rules and plan):
  - Runs ONLY on the host via apps/cli/scrape_x.py, never inside the research graph
    or Docker workers (slim images have no browser binaries).
  - Uses a logged-in Playwright storage_state exported by the user (throwaway
    account recommended — scraping violates X ToS and risks account flags).
  - Polite by design: small handle list, sequential fetches, configurable delay.

parse_timeline_html() is a pure function so it can be unit-tested on HTML
fixtures without a browser.
"""

import asyncio
import datetime as dt
import re
from datetime import UTC, datetime
from typing import Any

from core.logging import get_logger

from social.schemas import SocialPostData

logger = get_logger(__name__)

_CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,5})\b")
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
_TWEET_URL_RE = re.compile(r"/([^/]+)/status/(\d+)")


def extract_cashtags(body: str) -> set[str]:
    """Return upper-cased cashtag symbols mentioned in a post body."""
    return {m.group(1).upper() for m in _CASHTAG_RE.finditer(body)}


def _parse_count(text: str) -> int:
    """Parse X-style counts: '1,234' / '5.6K' / '1.2M' → int."""
    cleaned = text.strip().replace(",", "")
    if not cleaned:
        return 0
    multiplier = 1
    if cleaned[-1] in ("K", "k"):
        multiplier, cleaned = 1_000, cleaned[:-1]
    elif cleaned[-1] in ("M", "m"):
        multiplier, cleaned = 1_000_000, cleaned[:-1]
    try:
        return int(float(cleaned) * multiplier)
    except ValueError:
        return 0


def parse_timeline_html(html: str, handle: str) -> list[SocialPostData]:
    """Extract tweets from a rendered X profile timeline. Pure — no browser.

    Selector notes: X renders each tweet as <article data-testid="tweet">; the
    permalink <a href="/{handle}/status/{id}"> carries a <time datetime="...">;
    text lives under data-testid="tweetText"; counts use aria-labels on the
    reply/retweet/like group. DOM churns often — parser is defensive and skips
    anything malformed rather than raising.
    """
    from html.parser import HTMLParser

    class _TweetExtractor(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.tweets: list[dict[str, Any]] = []
            self._current: dict[str, Any] | None = None
            self._in_text = False
            self._depth = 0
            self._text_depth = 0

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            attrs_d = dict(attrs)
            testid = attrs_d.get("data-testid")
            if tag == "article" and testid == "tweet":
                self._current = {"body_parts": []}
                self._depth = 1
                return
            if self._current is None:
                return
            self._depth += 1
            if testid == "tweetText":
                self._in_text = True
                self._text_depth = self._depth
            elif tag == "a" and (href := attrs_d.get("href")):
                m = _TWEET_URL_RE.search(href)
                if m and "status_id" not in self._current:
                    self._current["author"] = m.group(1)
                    self._current["status_id"] = m.group(2)
                    self._current["url"] = f"https://x.com{href}"
            elif tag == "time" and (ts := attrs_d.get("datetime")):
                self._current.setdefault("datetime", ts)
            elif tag == "div" and testid in ("reply", "retweet", "like"):
                label = attrs_d.get("aria-label") or ""
                num = re.search(r"[\d.,]+[KkMm]?", label)
                self._current[f"count_{testid}"] = _parse_count(num.group(0)) if num else 0

        def handle_data(self, data: str) -> None:
            if self._current is not None and self._in_text:
                self._current["body_parts"].append(data)

        def handle_endtag(self, tag: str) -> None:
            if self._current is None:
                return
            if self._in_text and self._depth == self._text_depth:
                self._in_text = False
            self._depth -= 1
            if tag == "article" and self._depth <= 0:
                self.tweets.append(self._current)
                self._current = None
                self._in_text = False

    extractor = _TweetExtractor()
    try:
        extractor.feed(html)
    except Exception as exc:
        logger.warning("x_parse_failed", handle=handle, error=str(exc))
        return []

    posts: list[SocialPostData] = []
    for raw in extractor.tweets:
        status_id = raw.get("status_id")
        body = "".join(raw.get("body_parts") or []).strip()
        ts = raw.get("datetime")
        if not status_id or not body or not ts:
            continue
        try:
            posted_at = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except ValueError:
            continue
        if posted_at.tzinfo is None:
            posted_at = posted_at.replace(tzinfo=UTC)
        posts.append(
            SocialPostData(
                provider_post_id=str(status_id),
                author_handle=str(raw.get("author") or handle),
                body=body,
                url=raw.get("url"),
                posted_at=posted_at,
                sentiment_score=0.0,  # X gives no sentiment label; LLM analysis scores it
                likes_count=int(raw.get("count_like") or 0),
                reposts_count=int(raw.get("count_retweet") or 0),
                replies_count=int(raw.get("count_reply") or 0),
            )
        )
    return posts


class XScraper:
    """Scrapes configured X handles with a logged-in Playwright session.

    Not a SocialProvider: it fetches per-handle (not per-symbol) and tags posts
    to symbols via cashtags. The CLI persists results; the research graph only
    reads them from the DB.
    """

    def __init__(
        self,
        handles: list[str],
        session_state_path: str,
        min_delay_seconds: int = 5,
        max_posts_per_handle: int = 20,
    ) -> None:
        self._handles = [h.lstrip("@").strip() for h in handles if h.strip()]
        self._session_state_path = session_state_path
        self._min_delay = min_delay_seconds
        self._max_posts = max_posts_per_handle

    async def scrape(self, symbols: list[str]) -> dict[str, list[SocialPostData]]:
        """Return {symbol: posts} for posts mentioning $SYMBOL from configured handles."""
        from playwright.async_api import async_playwright

        wanted = {s.upper() for s in symbols}
        by_symbol: dict[str, list[SocialPostData]] = {s: [] for s in wanted}

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                storage_state=self._session_state_path or None,
                user_agent=_USER_AGENT,
            )
            page = await context.new_page()
            for i, handle in enumerate(self._handles):
                if i > 0:
                    await asyncio.sleep(self._min_delay)
                try:
                    await page.goto(
                        f"https://x.com/{handle}", wait_until="domcontentloaded", timeout=30_000
                    )
                    await page.wait_for_selector("article", timeout=15_000)
                    html = await page.content()
                except Exception as exc:
                    logger.warning("x_scrape_handle_failed", handle=handle, error=str(exc))
                    continue

                posts = parse_timeline_html(html, handle)[: self._max_posts]
                matched = 0
                for post in posts:
                    for symbol in extract_cashtags(post.body) & wanted:
                        by_symbol[symbol].append(post)
                        matched += 1
                logger.info(
                    "x_scrape_handle_done", handle=handle, posts=len(posts), matched=matched
                )
            await browser.close()

        return by_symbol


def recent_only(
    posts: list[SocialPostData], days: int, now: datetime | None = None
) -> list[SocialPostData]:
    """Filter posts to the lookback window."""
    cutoff = (now or datetime.now(UTC)) - dt.timedelta(days=days)
    return [p for p in posts if p.posted_at >= cutoff]
