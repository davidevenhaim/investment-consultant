"""Pydantic output schemas for LLM structured analysis.

SAFETY RULES enforced by schema:
- extra="forbid" on ALL models — extra fields (action, score, recommendation, etc.) fail validation.
- confidence_penalty capped at 0.15 per component.
- total_confidence_penalty capped at 0.25 — computed by service, never LLM-set.
- No buy/sell/hold/action/score fields anywhere.
"""
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ThesisAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    short_thesis: str
    bullish_points: list[str]
    bearish_points: list[str]
    what_changed_since_last_run: list[str]
    previous_thesis_alignment: Literal[
        "NO_PREVIOUS_THESIS", "UNCHANGED", "IMPROVED", "WORSENED", "MIXED"
    ]
    confidence: float = Field(ge=0.0, le=1.0)


class RiskAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    key_risks: list[str]
    valuation_risks: list[str]
    business_risks: list[str]
    technical_risks: list[str]
    near_term_watch_items: list[str]
    confidence: float = Field(ge=0.0, le=1.0)


class MissingDetailsAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    blocking_missing_details: list[str]
    non_blocking_missing_details: list[str]
    should_reduce_confidence: bool
    confidence_penalty: Annotated[float, Field(ge=0.0, le=0.15)]
    confidence: float = Field(ge=0.0, le=1.0)


class CriticReview(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: str
    strongest_counterargument: str
    weak_points_in_analysis: list[str]
    potential_overclaims: list[str]
    should_cap_strong_buy: bool
    should_reduce_confidence: bool
    confidence_penalty: Annotated[float, Field(ge=0.0, le=0.15)]
    confidence: float = Field(ge=0.0, le=1.0)


class CombinedLLMAnalysis(BaseModel):
    """
    Full LLM analysis output. Constructed by service — never directly from LLM output.
    total_confidence_penalty is always computed, never LLM-set.
    """

    thesis: ThesisAnalysis
    risk: RiskAnalysis
    missing_details: MissingDetailsAnalysis
    critic: CriticReview
    llm_enabled: bool
    llm_model: str | None = None
    total_confidence_penalty: Annotated[float, Field(ge=0.0, le=0.25)]
    analysis_quality_score: float = Field(ge=0.0, le=1.0)


# ── Helpers ───────────────────────────────────────────────────────────────────

_FORBIDDEN_KEYS = frozenset(
    {"action", "score", "recommendation", "buy", "sell", "hold", "target_price", "position_size"}
)


def check_forbidden_keys(raw: dict[str, Any]) -> list[str]:
    """Return list of forbidden keys found in raw dict (top-level and in sub-dicts)."""
    found: list[str] = []
    for section_val in raw.values():
        if isinstance(section_val, dict):
            for key in section_val:
                if key.lower() in _FORBIDDEN_KEYS:
                    found.append(key)
    for key in raw:
        if key.lower() in _FORBIDDEN_KEYS:
            found.append(key)
    return found


def _empty_thesis(symbol: str) -> ThesisAnalysis:
    return ThesisAnalysis(
        symbol=symbol,
        short_thesis="LLM analysis not available.",
        bullish_points=[],
        bearish_points=[],
        what_changed_since_last_run=[],
        previous_thesis_alignment="NO_PREVIOUS_THESIS",
        confidence=0.0,
    )


def _empty_risk(symbol: str) -> RiskAnalysis:
    return RiskAnalysis(
        symbol=symbol,
        key_risks=[],
        valuation_risks=[],
        business_risks=[],
        technical_risks=[],
        near_term_watch_items=[],
        confidence=0.0,
    )


def _empty_missing(symbol: str) -> MissingDetailsAnalysis:
    return MissingDetailsAnalysis(
        symbol=symbol,
        blocking_missing_details=[],
        non_blocking_missing_details=[],
        should_reduce_confidence=False,
        confidence_penalty=0.0,
        confidence=0.0,
    )


def _empty_critic(symbol: str) -> CriticReview:
    return CriticReview(
        symbol=symbol,
        strongest_counterargument="",
        weak_points_in_analysis=[],
        potential_overclaims=[],
        should_cap_strong_buy=False,
        should_reduce_confidence=False,
        confidence_penalty=0.0,
        confidence=0.0,
    )


def empty_analysis(symbol: str, llm_model: str | None = None) -> CombinedLLMAnalysis:
    """Return a valid empty analysis for when LLM is disabled or failed."""
    return CombinedLLMAnalysis(
        thesis=_empty_thesis(symbol),
        risk=_empty_risk(symbol),
        missing_details=_empty_missing(symbol),
        critic=_empty_critic(symbol),
        llm_enabled=False,
        llm_model=llm_model,
        total_confidence_penalty=0.0,
        analysis_quality_score=0.0,
    )
