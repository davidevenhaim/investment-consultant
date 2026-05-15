"""Pydantic schemas for local LLM (Ollama) input and output."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class OllamaMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


# ── Analysis output schema ─────────────────────────────────────────────────────


class PerformanceDriver(BaseModel):
    title: str
    explanation: str
    symbols: list[str] = Field(default_factory=list)


class RiskNote(BaseModel):
    title: str
    explanation: str
    severity: Literal["LOW", "MEDIUM", "HIGH"]


class TradeCommentary(BaseModel):
    symbol: str
    comment: str


class BacktestAnalysisOutput(BaseModel):
    headline: str
    plain_english_summary: str
    performance_drivers: list[PerformanceDriver] = Field(default_factory=list)
    risk_notes: list[RiskNote] = Field(default_factory=list)
    trade_commentary: list[TradeCommentary] = Field(default_factory=list)
    what_the_advisor_should_learn: list[str] = Field(default_factory=list)
    data_quality_warnings: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)


# ── Error types ────────────────────────────────────────────────────────────────


class OllamaDisabledError(Exception):
    """Raised when OLLAMA_ENABLED=false."""


class OllamaConnectionError(Exception):
    """Raised when Ollama is unreachable or returns an HTTP error."""


class OllamaParseError(Exception):
    """Raised when Ollama response is not valid JSON or fails schema validation."""
