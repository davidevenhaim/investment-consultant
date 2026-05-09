"""Idempotent seed script. Safe to run multiple times."""

import asyncio
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "packages"))

from core.config import get_settings
from core.logging import get_logger, setup_logging
from db.session import get_session_factory, init_db

setup_logging()
logger = get_logger(__name__)

# Typed constants — avoids mypy inferring Collection[str] from mixed-value dicts
_STRATEGY_VERSION: str = "v0.1.0"
_STRATEGY_DESCRIPTION: str = "Initial strategy — deterministic scoring, no ML."
_STRATEGY_SCORING_CONFIG: dict[str, Any] = {
    "version": "v0.1.0",
    "score_weights": {
        "technical": 20,
        "risk": 15,
        "fundamental": 20,
        "valuation": 15,
        "news": 15,
        "portfolio_fit": 15,
    },
    "stub_scores": {
        "news": 5,
        "portfolio_fit": 7,
    },
    "action_thresholds": {
        "strong_buy": 85,
        "buy_candidate": 70,
        "hold": 50,
        "reduce": 35,
    },
    "data_quality_thresholds": {
        "minimum_to_buy": 0.75,
        "minimum_to_recommend": 0.50,
    },
    "confidence_thresholds": {
        "minimum_to_buy": 0.65,
    },
    "action_caps": {
        "missing_news": "BUY_CANDIDATE",
        "missing_portfolio_context": "BUY_CANDIDATE",
        "low_fundamentals_quality": "WATCHLIST",
        "low_market_data_quality": "WATCHLIST",
    },
}
_STRATEGY_RISK_POLICY: dict[str, Any] = {
    "max_single_stock_weight": 0.15,
    "min_confidence_to_buy": 0.65,
    "min_data_quality": 0.50,
    "no_buy_before_earnings": True,
}

_PROMPT_NAME: str = "research"
_PROMPT_VERSION: str = "v0.1.0"
_PROMPT_TEXT: str = "Placeholder — implemented in M7."

_WATCHLIST: list[dict[str, str]] = [
    {"symbol": "AAPL", "company_name": "Apple Inc.", "exchange": "NASDAQ"},
    {"symbol": "NVDA", "company_name": "NVIDIA Corporation", "exchange": "NASDAQ"},
    {"symbol": "TSLA", "company_name": "Tesla, Inc.", "exchange": "NASDAQ"},
]


async def seed() -> None:
    settings = get_settings()
    init_db(settings.database_url)
    factory = get_session_factory()

    from db.models import InvestorProfile  # noqa: PLC0415
    from db.repositories import (  # noqa: PLC0415
        InvestorProfileRepository,
        PromptVersionRepository,
        StrategyVersionRepository,
        WatchlistRepository,
    )
    from sqlalchemy import select  # noqa: PLC0415

    async with factory() as session:
        sv_repo = StrategyVersionRepository(session)
        existing_sv = await sv_repo.get_by_version(_STRATEGY_VERSION)
        if existing_sv is None:
            sv = await sv_repo.create(
                version=_STRATEGY_VERSION,
                description=_STRATEGY_DESCRIPTION,
                scoring_config=_STRATEGY_SCORING_CONFIG,
                risk_policy=_STRATEGY_RISK_POLICY,
                is_active=True,
            )
            logger.info("seed_strategy_created", version=sv.version)
        else:
            # Update config if stale: missing action_thresholds (old M4 format) or stale stub_scores
            existing_cfg = existing_sv.scoring_config_json or {}
            current_news_stub = existing_cfg.get("stub_scores", {}).get("news", 9)
            needs_update = (
                "action_thresholds" not in existing_cfg
                or current_news_stub != _STRATEGY_SCORING_CONFIG["stub_scores"]["news"]
            )
            if needs_update:
                existing_sv.scoring_config_json = _STRATEGY_SCORING_CONFIG
                existing_sv.risk_policy_json = _STRATEGY_RISK_POLICY
                await session.flush()
                logger.info("seed_strategy_config_updated", version=existing_sv.version)
            else:
                logger.info("seed_strategy_exists", version=existing_sv.version)

        pv_repo = PromptVersionRepository(session)
        existing_pv = await pv_repo.get_by_name_version(_PROMPT_NAME, _PROMPT_VERSION)
        if existing_pv is None:
            pv = await pv_repo.create(
                name=_PROMPT_NAME,
                version=_PROMPT_VERSION,
                prompt_text=_PROMPT_TEXT,
                is_active=True,
            )
            logger.info("seed_prompt_created", name=pv.name, version=pv.version)
        else:
            logger.info("seed_prompt_exists", name=existing_pv.name)

        result = await session.execute(
            select(InvestorProfile).where(InvestorProfile.name == "default").limit(1)
        )
        if result.scalar_one_or_none() is None:
            ip_repo = InvestorProfileRepository(session)
            await ip_repo.create(name="default", is_active=True)
            logger.info("seed_investor_profile_created")
        else:
            logger.info("seed_investor_profile_exists")

        wl_repo = WatchlistRepository(session)
        for entry in _WATCHLIST:
            existing = await wl_repo.get_by_symbol(entry["symbol"])
            if existing is None:
                ws = await wl_repo.create(**entry)
                logger.info("seed_watchlist_added", symbol=ws.symbol)
            else:
                logger.info("seed_watchlist_exists", symbol=existing.symbol)

        await session.commit()
        logger.info("seed_complete")


if __name__ == "__main__":
    asyncio.run(seed())
