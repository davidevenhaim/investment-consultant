"""LLM analysis node — single node, one API call, returns CombinedLLMAnalysis."""

from collections.abc import Callable
from typing import Any

from ai.interfaces import LLMClient
from ai.prompts import build_context, format_prompt
from ai.schemas import empty_analysis
from ai.service import run_llm_analysis
from core.config import get_settings
from core.logging import get_logger
from db.repositories import PromptVersionRepository
from sqlalchemy.ext.asyncio import AsyncSession

from research_graph.state import ResearchState

logger = get_logger(__name__)


def make_llm_analysis(
    session: AsyncSession,
    llm_client: LLMClient | None = None,
) -> Callable[[ResearchState], Any]:
    """
    Factory that binds session and optional LLM client.
    Graph shape is always stable — node always runs.
    If LLM is disabled or unavailable, writes empty CombinedLLMAnalysis(llm_enabled=False).
    """

    async def llm_analysis(state: ResearchState) -> dict[str, Any]:
        symbol = state["symbol"]
        settings = get_settings()

        # Resolve client: injected (for tests) takes priority; fall back to settings.
        # llm_provider routes between the Claude API and a local Ollama model.
        client = llm_client
        model = settings.llm_model
        if client is None:
            if not settings.llm_enabled:
                logger.info("llm_analysis_skipped_disabled", symbol=symbol)
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
                    logger.warning("llm_analysis_skipped_no_key", symbol=symbol)
                    return _disabled_result(symbol)
                from ai.client import AnthropicLLMClient

                client = AnthropicLLMClient(
                    api_key=settings.anthropic_api_key,
                    model=settings.llm_model,
                    timeout_seconds=settings.llm_timeout_seconds,
                    max_retries=settings.llm_max_retries,
                )

        # Load active prompt version from DB
        prompt_version_id: str | None = None
        try:
            pv_repo = PromptVersionRepository(session)
            pv = await pv_repo.get_active("combined_analysis")
            if pv is None:
                logger.warning("llm_analysis_no_prompt_version", symbol=symbol)
                return _disabled_result(
                    symbol, warnings=["No active combined_analysis prompt found."]
                )
            template = pv.prompt_text
            prompt_version_id = str(pv.id)
        except Exception as exc:
            logger.warning("llm_analysis_prompt_load_failed", symbol=symbol, error=str(exc))
            return _disabled_result(symbol, warnings=[f"Prompt load failed: {exc}"])

        # Build and format prompt
        context = build_context(dict(state))
        prompt = format_prompt(template, symbol=symbol, context=context)

        logger.info("llm_analysis_starting", symbol=symbol, model=model)
        analysis, warnings = await run_llm_analysis(
            symbol=symbol,
            prompt=prompt,
            client=client,
            model=model,
        )

        penalty = analysis.total_confidence_penalty if analysis.llm_enabled else 0.0

        result: dict[str, Any] = {
            "llm_analysis": analysis,
            "llm_confidence_penalty": penalty,
        }
        if warnings:
            result["llm_warnings"] = warnings
        if prompt_version_id:
            result["llm_prompt_version_id"] = prompt_version_id
        return result

    return llm_analysis


def _disabled_result(symbol: str, warnings: list[str] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "llm_analysis": empty_analysis(symbol),
        "llm_confidence_penalty": 0.0,
    }
    if warnings:
        result["llm_warnings"] = warnings
    return result
