"""Idempotent seed script. Safe to run multiple times."""

import asyncio
import sys
import uuid
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

_COMBINED_ANALYSIS_NAME: str = "combined_analysis"
_COMBINED_ANALYSIS_VERSION: str = "v0.1.0"
_COMBINED_ANALYSIS_PROMPT: str = """\
CRITICAL RULES — READ BEFORE RESPONDING:
1. You are a research analyst. You do NOT make final buy/sell/hold decisions.
2. Do NOT output any field named "action", "recommendation", "buy", "sell", "hold",
   "target_price", or "position_size". These fields will cause validation failure.
3. Do NOT invent news, earnings events, analyst ratings, insider transactions, or filings.
   If you do not have data for something, say it is missing.
4. Do NOT speculate beyond the data provided in this context.
5. Base all analysis ONLY on the data provided below.
6. News data is NOT available yet. Do not reference news events.
7. Portfolio context is NOT available yet. Do not reference position size.
8. Respond ONLY with valid JSON matching the schema exactly. No preamble. No markdown.
9. Debt-to-equity values in the context are already normalized ratios (e.g., 0.80x means 80%).
   Do not convert or re-interpret them.

=== RESEARCH CONTEXT FOR {{SYMBOL}} ===
{{CONTEXT}}

=== REQUIRED JSON SCHEMA ===
Respond with a single JSON object with exactly these top-level keys:
"thesis", "risk", "missing_details", "critic"

thesis:
{
  "symbol": string,
  "short_thesis": string (1-2 sentences, evidence-based only),
  "bullish_points": list[string] (max 5, data-supported only),
  "bearish_points": list[string] (max 5, data-supported only),
  "what_changed_since_last_run": list[string] (compare to previous memory if available),
  "previous_thesis_alignment": one of ["NO_PREVIOUS_THESIS","UNCHANGED",
    "IMPROVED","WORSENED","MIXED"],
  "confidence": float between 0.0 and 1.0
}

risk:
{
  "symbol": string,
  "key_risks": list[string] (top 3-5 risks, data-based),
  "valuation_risks": list[string],
  "business_risks": list[string],
  "technical_risks": list[string],
  "near_term_watch_items": list[string],
  "confidence": float between 0.0 and 1.0
}

missing_details:
{
  "symbol": string,
  "blocking_missing_details": list[string] (items that would change the analysis),
  "non_blocking_missing_details": list[string] (items that would help but aren't blocking),
  "should_reduce_confidence": boolean,
  "confidence_penalty": float between 0.0 and 0.15 (how much to reduce confidence),
  "confidence": float between 0.0 and 1.0
}

critic:
{
  "symbol": string,
  "strongest_counterargument": string (best argument AGAINST the bullish thesis),
  "weak_points_in_analysis": list[string],
  "potential_overclaims": list[string],
  "should_cap_strong_buy": boolean (true only if analysis quality is very low or risks are extreme),
  "should_reduce_confidence": boolean,
  "confidence_penalty": float between 0.0 and 0.15,
  "confidence": float between 0.0 and 1.0
}

Respond now with only the JSON object. No other text.\
"""

_SOCIAL_SENTIMENT_NAME: str = "social_sentiment_analysis"
_SOCIAL_SENTIMENT_VERSION: str = "v0.1.0"
_SOCIAL_SENTIMENT_PROMPT: str = """\
CRITICAL RULES — READ BEFORE RESPONDING:
1. You are a social sentiment analyst. You do NOT make buy/sell/hold decisions.
2. Do NOT output any field named "action", "recommendation", "buy", "sell", "hold",
   "target_price", "position_size", or "score". These fields cause validation failure.
3. Do NOT invent posts, events, or facts. Base analysis ONLY on the posts provided.
4. Social posts are unverified opinions — treat them as sentiment signals, not facts.
5. Flag hype, coordinated promotion, or manipulation patterns if you see them.
6. Respond ONLY with valid JSON matching the schema exactly. No preamble. No markdown.

=== SOCIAL CONTEXT FOR {{SYMBOL}} ===
{{CONTEXT}}

=== REQUIRED JSON SCHEMA ===
Respond with a single JSON object with exactly these keys:
{
  "symbol": string,
  "overall_sentiment": one of ["BULLISH","BEARISH","MIXED","NEUTRAL"],
  "key_themes": list[string] (max 5, recurring topics across posts),
  "hype_or_manipulation_flags": list[string] (empty if none observed),
  "risk_flags": list[string] (risks mentioned or implied by posts, empty if none),
  "divergence_from_news": string (how social sentiment differs from the news score,
    empty string if aligned or no news data),
  "should_reduce_confidence": boolean (true if posts look like hype/manipulation
    or are too sparse to trust),
  "confidence_penalty": float between 0.0 and 0.15,
  "confidence": float between 0.0 and 1.0
}

Respond now with only the JSON object. No other text.\
"""

_WATCHLIST: list[dict[str, str]] = [
    {"symbol": "AAPL", "company_name": "Apple Inc.", "exchange": "NASDAQ"},
    {"symbol": "NVDA", "company_name": "NVIDIA Corporation", "exchange": "NASDAQ"},
    {"symbol": "TSLA", "company_name": "Tesla, Inc.", "exchange": "NASDAQ"},
]
_DEV_DEFAULT_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


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

        # M7: combined_analysis prompt for LLM structured analysis node
        existing_ca = await pv_repo.get_by_name_version(
            _COMBINED_ANALYSIS_NAME, _COMBINED_ANALYSIS_VERSION
        )
        if existing_ca is None:
            from ai.schemas import CombinedLLMAnalysis  # noqa: PLC0415

            ca = await pv_repo.create(
                name=_COMBINED_ANALYSIS_NAME,
                version=_COMBINED_ANALYSIS_VERSION,
                prompt_text=_COMBINED_ANALYSIS_PROMPT,
                output_schema=CombinedLLMAnalysis.model_json_schema(),
                is_active=True,
            )
            logger.info("seed_combined_analysis_prompt_created", name=ca.name, version=ca.version)
        else:
            logger.info("seed_combined_analysis_prompt_exists", name=existing_ca.name)

        # Social sentiment prompt for social LLM analysis node
        existing_ss = await pv_repo.get_by_name_version(
            _SOCIAL_SENTIMENT_NAME, _SOCIAL_SENTIMENT_VERSION
        )
        if existing_ss is None:
            from ai.schemas import SocialSentimentAnalysis  # noqa: PLC0415

            ss = await pv_repo.create(
                name=_SOCIAL_SENTIMENT_NAME,
                version=_SOCIAL_SENTIMENT_VERSION,
                prompt_text=_SOCIAL_SENTIMENT_PROMPT,
                output_schema=SocialSentimentAnalysis.model_json_schema(),
                is_active=True,
            )
            logger.info("seed_social_sentiment_prompt_created", name=ss.name, version=ss.version)
        else:
            logger.info("seed_social_sentiment_prompt_exists", name=existing_ss.name)

        result = await session.execute(
            select(InvestorProfile)
            .where(
                InvestorProfile.name == "default",
                InvestorProfile.user_id == _DEV_DEFAULT_USER_ID,
            )
            .limit(1)
        )
        if result.scalar_one_or_none() is None:
            ip_repo = InvestorProfileRepository(session)
            await ip_repo.create(
                user_id=_DEV_DEFAULT_USER_ID,
                name="default",
                is_active=True,
            )
            logger.info("seed_investor_profile_created")
        else:
            logger.info("seed_investor_profile_exists")

        wl_repo = WatchlistRepository(session)
        for entry in _WATCHLIST:
            existing = await wl_repo.get_by_symbol(
                entry["symbol"],
                user_id=_DEV_DEFAULT_USER_ID,
            )
            if existing is None:
                ws = await wl_repo.create(**entry, user_id=_DEV_DEFAULT_USER_ID)
                logger.info("seed_watchlist_added", symbol=ws.symbol)
            else:
                logger.info("seed_watchlist_exists", symbol=existing.symbol)

        # M9: Default portfolio account + positions
        from db.repositories import (  # noqa: PLC0415
            PortfolioAccountRepository,
            PortfolioPositionRepository,
        )
        from portfolio.service import (  # noqa: PLC0415
            build_portfolio_snapshot,
            refresh_portfolio_prices,
        )

        acc_repo = PortfolioAccountRepository(session)
        account = await acc_repo.get_default(user_id=_DEV_DEFAULT_USER_ID)
        if account is None:
            account = await acc_repo.create(
                name="Default Manual Portfolio",
                account_type="MANUAL",
                cash_balance=10000.0,
                user_id=_DEV_DEFAULT_USER_ID,
            )
            logger.info("seed_portfolio_account_created", account_id=str(account.id))
        else:
            logger.info("seed_portfolio_account_exists", account_id=str(account.id))

        seed_positions: list[tuple[str, float, float]] = [
            ("AAPL", 10.0, 190.0),
            ("NVDA", 5.0, 120.0),
            ("TSLA", 3.0, 250.0),
        ]
        pos_repo = PortfolioPositionRepository(session)
        for sym, qty, cost in seed_positions:
            existing_pos = await pos_repo.get_by_symbol(account.id, sym)
            if existing_pos is None:
                await pos_repo.upsert_position(
                    account_id=account.id,
                    symbol=sym,
                    quantity=qty,
                    average_cost=cost,
                )
                logger.info("seed_position_added", symbol=sym)
            else:
                logger.info("seed_position_exists", symbol=sym)

        # Refresh prices and build snapshot
        await session.flush()
        await refresh_portfolio_prices(session, account.id)
        await build_portfolio_snapshot(session, account.id)
        logger.info("seed_portfolio_snapshot_built")

        await session.commit()
        logger.info("seed_complete")


if __name__ == "__main__":
    asyncio.run(seed())
