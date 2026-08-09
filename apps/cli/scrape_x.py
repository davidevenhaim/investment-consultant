"""CLI: scrape configured X handles and persist cashtag-matched posts.

Host-only (needs Playwright browsers — not installed in Docker images).

Usage:
    python -m apps.cli.scrape_x --login
        One-time: opens a headed browser; log in to X manually, then press
        Enter in the terminal to save the session to X_SESSION_STATE_PATH.

    python -m apps.cli.scrape_x --symbols AAPL,NVDA
        Scrapes handles from X_SCRAPE_ACCOUNTS, keeps posts mentioning the
        given cashtags, upserts into social_posts.
"""

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "packages"))

from core.config import get_settings
from core.logging import get_logger, setup_logging
from db.session import get_session_factory, init_db

setup_logging()
logger = get_logger(__name__)

_X_PROVIDER_NAME = "x"


async def _login() -> int:
    from playwright.async_api import async_playwright

    settings = get_settings()
    state_path = settings.x_session_state_path
    if not state_path:
        print("ERROR: set X_SESSION_STATE_PATH in .env first", file=sys.stderr)
        return 1

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://x.com/login")
        print("Log in to X in the opened browser window, then press Enter here...")
        await asyncio.to_thread(input)
        await context.storage_state(path=state_path)
        await browser.close()

    print(f"Session saved to {state_path}")
    return 0


async def _scrape(symbols: list[str]) -> int:
    from social.provider_x import XScraper, recent_only
    from social.repository import SocialPostRepository

    settings = get_settings()
    handles = [h for h in settings.x_scrape_accounts.split(",") if h.strip()]
    if not handles:
        print("ERROR: X_SCRAPE_ACCOUNTS is empty — nothing to scrape", file=sys.stderr)
        return 1
    if not settings.x_session_state_path or not Path(settings.x_session_state_path).exists():
        print(
            "ERROR: no session state found — run `python -m apps.cli.scrape_x --login` first",
            file=sys.stderr,
        )
        return 1

    scraper = XScraper(
        handles=handles,
        session_state_path=settings.x_session_state_path,
        min_delay_seconds=settings.x_scrape_min_delay_seconds,
    )
    by_symbol = await scraper.scrape(symbols)

    init_db(settings.database_url)
    factory = get_session_factory()
    total = 0
    async with factory() as session:
        repo = SocialPostRepository(session)
        for symbol, posts in by_symbol.items():
            posts = recent_only(posts, days=settings.social_lookback_days)
            if not posts:
                continue
            inserted = await repo.upsert_posts(
                symbol=symbol, provider=_X_PROVIDER_NAME, posts=posts
            )
            total += len(inserted)
            logger.info(
                "x_posts_persisted", symbol=symbol, fetched=len(posts), inserted=len(inserted)
            )
        await session.commit()

    print(f"Done. {total} new post(s) persisted.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape X handles into social_posts")
    parser.add_argument("--login", action="store_true", help="save a logged-in session state")
    parser.add_argument("--symbols", type=str, default="", help="comma-separated cashtags to keep")
    args = parser.parse_args()

    if args.login:
        return asyncio.run(_login())

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
    if not symbols:
        parser.error("--symbols required (e.g. --symbols AAPL,NVDA) unless --login")
    return asyncio.run(_scrape(symbols))


if __name__ == "__main__":
    raise SystemExit(main())
