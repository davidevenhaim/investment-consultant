"""Ollama-powered advisor backtest analyst service."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from core.config import get_settings
from db.models import AdvisorBacktestAnalysis, AdvisorBacktestRun
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from local_llm.ollama_client import OllamaClient
from local_llm.schemas import (
    BacktestAnalysisOutput,
    OllamaConnectionError,
    OllamaDisabledError,
    OllamaMessage,
    OllamaParseError,
)

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_PROMPT_VERSION = "ollama_backtest_analyst_v1"

_SYSTEM_PROMPT = """You are a cautious investment research analyst reviewing a simulated backtest.

STRICT RULES — follow all:
1. Do NOT invent trades, prices, or symbols absent from the input.
2. Do NOT claim causality beyond what the data shows.
3. Do NOT give personalized financial advice or recommend real trades.
4. If assumptions_json shows seeded/synthetic recommendations, state this in data_quality_warnings.
5. Distinguish "outperformed benchmark in this simulation" from "strategy is proven to work".
6. Warn about overfitting in risk_notes when total_trades < 10.
7. Set confidence (0.0–1.0) based on data quality and sample size.

Return ONLY valid JSON matching this exact schema — no prose outside the JSON:
{
  "headline": "<one-sentence result summary>",
  "plain_english_summary": "<2–4 sentences: what happened, why it matters>",
  "performance_drivers": [
    {"title": "string", "explanation": "string", "symbols": ["AAPL"]}
  ],
  "risk_notes": [
    {"title": "string", "explanation": "string", "severity": "LOW|MEDIUM|HIGH"}
  ],
  "trade_commentary": [
    {"symbol": "AAPL", "comment": "string"}
  ],
  "what_the_advisor_should_learn": ["string"],
  "data_quality_warnings": ["string"],
  "confidence": 0.5
}"""


def _sample_equity_points(
    points: list[dict[str, Any]],
    max_extra: int = 5,
) -> list[dict[str, Any]]:
    """Return first + sampled interior + worst-drawdown + last — never the full curve."""
    if len(points) <= 2:
        return list(points)

    sorted_pts = sorted(points, key=lambda p: str(p.get("date", "")))
    first = sorted_pts[0]
    last = sorted_pts[-1]
    worst = min(sorted_pts, key=lambda p: float(p.get("drawdown_pct") or 0.0))

    interior = sorted_pts[1:-1]
    sampled: list[dict[str, Any]] = []
    if interior:
        step = max(1, len(interior) // max_extra)
        sampled = interior[::step][:max_extra]

    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for p in [first, *sampled, worst, last]:
        key = str(p.get("date", ""))
        if key not in seen:
            seen.add(key)
            result.append(p)

    return sorted(result, key=lambda p: str(p.get("date", "")))


def build_prompt_input(run: AdvisorBacktestRun) -> dict[str, Any]:
    """Build compact, JSON-serialisable dict from a loaded AdvisorBacktestRun."""
    all_equity: list[dict[str, Any]] = [
        {
            "date": str(ep.date),
            "equity": float(ep.equity),
            "cash": float(ep.cash),
            "positions_value": float(ep.positions_value),
            "drawdown_pct": float(ep.drawdown_pct) if ep.drawdown_pct is not None else None,
            "benchmark_value": (
                float(ep.benchmark_value) if ep.benchmark_value is not None else None
            ),
        }
        for ep in sorted(run.equity_points, key=lambda ep: ep.date)
    ]

    trades_compact: list[dict[str, Any]] = [
        {
            "date": (
                t.trade_date.strftime("%Y-%m-%d")
                if hasattr(t.trade_date, "strftime")
                else str(t.trade_date)
            ),
            "symbol": t.symbol,
            "action": t.action,
            "trade_type": t.trade_type,
            "price": float(t.price) if t.price is not None else None,
            "quantity": float(t.quantity) if t.quantity is not None else None,
            "cash_delta": float(t.cash_delta) if t.cash_delta is not None else None,
            "reason": t.reason,
        }
        for t in sorted(run.trades, key=lambda t: t.trade_date)
        if t.trade_type != "SKIP"
    ]

    skipped = sum(1 for t in run.trades if t.trade_type == "SKIP")
    initial = float(run.initial_cash)
    final = float(run.final_equity) if run.final_equity is not None else None
    pnl = round(final - initial, 4) if final is not None else None

    return {
        "start_date": str(run.start_date),
        "end_date": str(run.end_date),
        "initial_cash": initial,
        "final_equity": final,
        "profit_loss_amount": pnl,
        "total_return_pct": (
            float(run.total_return_pct) if run.total_return_pct is not None else None
        ),
        "benchmark_symbol": run.benchmark_symbol,
        "benchmark_return_pct": (
            float(run.benchmark_return_pct) if run.benchmark_return_pct is not None else None
        ),
        "relative_return_pct": (
            float(run.relative_return_pct) if run.relative_return_pct is not None else None
        ),
        "max_drawdown_pct": (
            float(run.max_drawdown_pct) if run.max_drawdown_pct is not None else None
        ),
        "total_trades": run.total_trades,
        "winning_trades": run.winning_trades,
        "losing_trades": run.losing_trades,
        "skipped_recommendations": skipped,
        "assumptions_json": run.assumptions_json,
        "trades": trades_compact,
        "equity_summary": _sample_equity_points(all_equity),
    }


def _build_user_message(prompt_input: dict[str, Any]) -> str:
    return (
        "Analyze this advisor backtest simulation and return your analysis as JSON:\n\n"
        + json.dumps(prompt_input, indent=2, default=str)
    )


async def generate_advisor_backtest_analysis(
    session: AsyncSession,
    user_id: uuid.UUID,
    advisor_backtest_run_id: uuid.UUID,
    force: bool = False,
) -> AdvisorBacktestAnalysis:
    """Generate (or return cached) Ollama analysis for an advisor backtest run.

    Raises:
        ValueError: run not found or belongs to different user.
        OllamaDisabledError: OLLAMA_ENABLED=false — caller should return 503 without persisting.
        OllamaConnectionError: Ollama unreachable — FAILED row is persisted before re-raising.
        OllamaParseError: bad JSON from Ollama — FAILED row is persisted before re-raising.
    """
    settings = get_settings()

    # 1. Verify ownership and load relationships
    result = await session.execute(
        select(AdvisorBacktestRun)
        .options(
            selectinload(AdvisorBacktestRun.trades),
            selectinload(AdvisorBacktestRun.equity_points),
        )
        .where(
            AdvisorBacktestRun.id == advisor_backtest_run_id,
            AdvisorBacktestRun.user_id == user_id,
        )
    )
    run = result.scalar_one_or_none()
    if run is None:
        raise ValueError("Advisor backtest run not found.")

    # 2. Return existing COMPLETED analysis when force=False
    if not force:
        existing_result = await session.execute(
            select(AdvisorBacktestAnalysis)
            .where(
                AdvisorBacktestAnalysis.advisor_backtest_run_id == advisor_backtest_run_id,
                AdvisorBacktestAnalysis.status == "COMPLETED",
            )
            .order_by(AdvisorBacktestAnalysis.created_at.desc())
            .limit(1)
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            return existing

    # 3. Raise without persisting when Ollama is disabled — per spec
    if not settings.ollama_enabled:
        raise OllamaDisabledError("Ollama is disabled (OLLAMA_ENABLED=false).")

    # 4. Build prompt
    prompt_input = build_prompt_input(run)
    client = OllamaClient(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        timeout=settings.ollama_timeout_seconds,
    )
    messages = [
        OllamaMessage(role="system", content=_SYSTEM_PROMPT),
        OllamaMessage(role="user", content=_build_user_message(prompt_input)),
    ]

    # 5. Call Ollama — persist FAILED on any error, then re-raise
    try:
        raw = await client.chat_json(messages)
        parsed = BacktestAnalysisOutput.model_validate(raw)
    except (OllamaConnectionError, OllamaParseError, Exception) as exc:
        if not isinstance(exc, (OllamaConnectionError, OllamaParseError)):
            # Unexpected parse/validation error — wrap so caller sees OllamaParseError
            exc = OllamaParseError(f"Schema validation failed: {exc}")
        failed = AdvisorBacktestAnalysis(
            user_id=user_id,
            advisor_backtest_run_id=advisor_backtest_run_id,
            provider="ollama",
            model=settings.ollama_model,
            prompt_version=_PROMPT_VERSION,
            status="FAILED",
            analysis_json={},
            prompt_input_json=prompt_input,
            error_message=str(exc),
        )
        session.add(failed)
        await session.flush()
        logger.error(
            "advisor_backtest_analysis_failed",
            extra={"run_id": str(advisor_backtest_run_id), "error": str(exc)},
        )
        raise exc

    analysis = AdvisorBacktestAnalysis(
        user_id=user_id,
        advisor_backtest_run_id=advisor_backtest_run_id,
        provider="ollama",
        model=settings.ollama_model,
        prompt_version=_PROMPT_VERSION,
        status="COMPLETED",
        analysis_json=parsed.model_dump(),
        prompt_input_json=prompt_input,
        error_message=None,
    )
    session.add(analysis)
    await session.flush()
    logger.info(
        "advisor_backtest_analysis_completed",
        extra={"run_id": str(advisor_backtest_run_id), "model": settings.ollama_model},
    )
    return analysis
