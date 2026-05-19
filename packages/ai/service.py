"""LLM analysis orchestrator — call + parse + validate + fallback."""

import json
from typing import Any

from core.errors import LLMError, LLMParseError
from core.logging import get_logger

from ai.interfaces import LLMClient
from ai.schemas import (
    CombinedLLMAnalysis,
    CriticReview,
    MissingDetailsAnalysis,
    RiskAnalysis,
    ThesisAnalysis,
    check_forbidden_keys,
    empty_analysis,
)

logger = get_logger(__name__)


def _compute_analysis_quality(
    thesis: ThesisAnalysis,
    risk: RiskAnalysis,
    missing: MissingDetailsAnalysis,
    critic: CriticReview,
) -> float:
    scores = [thesis.confidence, risk.confidence, missing.confidence, critic.confidence]
    return round(sum(scores) / len(scores), 3)


def _compute_total_penalty(missing: MissingDetailsAnalysis, critic: CriticReview) -> float:
    total = min(0.15, missing.confidence_penalty) + min(0.15, critic.confidence_penalty)
    return round(min(0.25, total), 4)


def _parse_and_validate(raw_text: str, symbol: str, model: str) -> CombinedLLMAnalysis:
    """
    Parse raw LLM JSON → validate each section → build CombinedLLMAnalysis.
    Raises LLMParseError on any parse/validation failure.
    """
    try:
        raw: dict[str, Any] = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise LLMParseError(f"LLM returned invalid JSON: {exc}", {"symbol": symbol}) from exc

    if not isinstance(raw, dict):
        raise LLMParseError("LLM response is not a JSON object.", {"symbol": symbol})

    # Explicit forbidden key check before Pydantic (belt-and-suspenders)
    forbidden = check_forbidden_keys(raw)
    if forbidden:
        raise LLMParseError(
            f"LLM response contains forbidden keys: {forbidden}",
            {"symbol": symbol, "forbidden": forbidden},
        )

    try:
        thesis = ThesisAnalysis.model_validate(raw["thesis"])
        risk = RiskAnalysis.model_validate(raw["risk"])
        missing = MissingDetailsAnalysis.model_validate(raw["missing_details"])
        critic = CriticReview.model_validate(raw["critic"])
    except (KeyError, Exception) as exc:
        raise LLMParseError(
            f"LLM response failed schema validation: {exc}", {"symbol": symbol}
        ) from exc

    total_penalty = _compute_total_penalty(missing, critic)
    quality = _compute_analysis_quality(thesis, risk, missing, critic)

    return CombinedLLMAnalysis(
        thesis=thesis,
        risk=risk,
        missing_details=missing,
        critic=critic,
        llm_enabled=True,
        llm_model=model,
        total_confidence_penalty=total_penalty,
        analysis_quality_score=quality,
    )


async def run_llm_analysis(
    symbol: str,
    prompt: str,
    client: LLMClient,
    model: str,
) -> tuple[CombinedLLMAnalysis, list[str]]:
    """
    Call LLM, parse, validate. Returns (analysis, warnings).
    On any failure returns (empty_analysis, [warning_message]) — never raises.
    """
    warnings: list[str] = []
    try:
        raw_text = await client.complete(prompt, max_tokens=2000)
        analysis = _parse_and_validate(raw_text, symbol, model)
        logger.info(
            "llm_analysis_ok",
            symbol=symbol,
            model=model,
            quality=analysis.analysis_quality_score,
            penalty=analysis.total_confidence_penalty,
        )
        return analysis, warnings
    except LLMError as exc:
        msg = f"LLM call failed for {symbol}: {exc.message}"
        logger.warning("llm_analysis_failed", symbol=symbol, error=exc.message)
        warnings.append(msg)
    except LLMParseError as exc:
        msg = f"LLM parse failed for {symbol}: {exc.message}"
        logger.warning("llm_parse_failed", symbol=symbol, error=exc.message)
        warnings.append(msg)
    except Exception as exc:
        msg = f"Unexpected LLM error for {symbol}: {exc}"
        logger.warning("llm_analysis_unexpected", symbol=symbol, error=str(exc))
        warnings.append(msg)

    return empty_analysis(symbol, model), warnings
