"""Social sentiment LLM analysis node — distinct prompt, evidence only.

Reads social_posts from state, asks the LLM (local qwen3 or Claude) for a
structured sentiment read (SocialSentimentAnalysis). Never scores, never
decides. Penalty flows through the confidence_penalties add-channel.
"""

from collections.abc import Callable
from typing import Any

from ai.interfaces import LLMClient
from ai.prompts import build_social_context, format_prompt
from ai.schemas import empty_social_analysis
from ai.service import run_social_llm_analysis
from core.config import get_settings
from core.logging import get_logger
from db.repositories import PromptVersionRepository
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.state import ResearchState

logger = get_logger(__name__)

_PROMPT_NAME = "social_sentiment_analysis"


def make_social_llm_analysis(
    session: AsyncSession,
    llm_client: LLMClient | None = None,
) -> Callable[[ResearchState], Any]:
    """
    Factory that binds session and optional LLM client.
    Graph shape stable — node always runs; skips cleanly when disabled,
    no posts, or no prompt version.
    """

    async def social_llm_analysis(state: ResearchState) -> dict[str, Any]:
        symbol = state["symbol"]
        settings = get_settings()

        social_posts = state.get("social_posts") or []
        if not social_posts:
            logger.info("social_llm_analysis_skipped_no_posts", symbol=symbol)
            return _disabled_result(symbol)

        client = llm_client
        model = settings.llm_model
        if client is None:
            if not settings.llm_enabled:
                logger.info("social_llm_analysis_skipped_disabled", symbol=symbol)
                return _disabled_result(symbol)
            if settings.llm_provider == "ollama":
                from ai.ollama_llm_client import OllamaLLMClient

                model = settings.ollama_research_model
                client = OllamaLLMClient(
                    base_url=settings.ollama_base_url,
                    model=model,
                    timeout_seconds=settings.ollama_research_timeout_seconds,
                )
            else:
                if not settings.anthropic_api_key:
                    logger.warning("social_llm_analysis_skipped_no_key", symbol=symbol)
                    return _disabled_result(symbol)
                from ai.client import AnthropicLLMClient

                client = AnthropicLLMClient(
                    api_key=settings.anthropic_api_key,
                    model=settings.llm_model,
                    timeout_seconds=settings.llm_timeout_seconds,
                    max_retries=settings.llm_max_retries,
                )

        try:
            pv_repo = PromptVersionRepository(session)
            pv = await pv_repo.get_active(_PROMPT_NAME)
            if pv is None:
                logger.warning("social_llm_analysis_no_prompt_version", symbol=symbol)
                return _disabled_result(
                    symbol, warnings=[f"No active {_PROMPT_NAME} prompt found."]
                )
            template = pv.prompt_text
        except Exception as exc:
            logger.warning("social_llm_analysis_prompt_load_failed", symbol=symbol, error=str(exc))
            return _disabled_result(symbol, warnings=[f"Social prompt load failed: {exc}"])

        context = build_social_context(dict(state))
        prompt = format_prompt(template, symbol=symbol, context=context)

        logger.info("social_llm_analysis_starting", symbol=symbol, model=model)
        analysis, warnings = await run_social_llm_analysis(
            symbol=symbol,
            prompt=prompt,
            client=client,
            model=model,
        )

        penalty = analysis.confidence_penalty if analysis.llm_enabled else 0.0

        result: dict[str, Any] = {
            "social_llm_analysis": analysis,
            "confidence_penalties": [penalty] if penalty > 0 else [],
        }
        if warnings:
            result["llm_warnings"] = warnings
        return result

    return social_llm_analysis


def _disabled_result(symbol: str, warnings: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "social_llm_analysis": empty_social_analysis(symbol),
        "confidence_penalties": [],
    }
    if warnings:
        result["llm_warnings"] = warnings
    return result
