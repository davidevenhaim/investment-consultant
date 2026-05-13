"""Backtesting service — outcome computation + learning event generation.

Design rules:
- Pure compute functions are synchronous and DB-free (easy to unit test).
- DB-bound functions are async and accept an AsyncSession.
- Never raise on missing data — return INSUFFICIENT_DATA instead.
- No live market-data API calls in this module; use price rows from DB.
- No LLM calls in M11 — all classifications are deterministic rules.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, Any

from backtesting.schemas import ForwardOutcome

if TYPE_CHECKING:
    import uuid

    from market_data.schemas import MarketPriceBar
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Outcome classification thresholds (conservative, easy to tune) ─────────

# A "significant" buy-side gain/loss relative to benchmark
_BUY_WIN_MIN_FORWARD_RETURN = 0.03          # +3 % absolute or better
_BUY_WIN_MIN_RELATIVE_RETURN = 0.0          # positive relative = WIN
_BUY_LOSS_MAX_FORWARD_RETURN = -0.03        # worse than -3 % = LOSS candidate
_BUY_LOSS_MAX_RELATIVE_RETURN = -0.05       # meaningfully underperforms benchmark

# HOLD: how much upside counts as "missed"
_HOLD_MISSED_UPSIDE_MIN = 0.10              # +10 % forward return after HOLD = MISSED_UPSIDE

# REDUCE / SELL / NO_ACTION: avoided-loss threshold
_REDUCE_AVOIDED_LOSS_MAX_FORWARD = -0.05    # price fell >5 % = AVOIDED_LOSS

# STOP_LOSS_LIKE drawdown threshold
_STOP_LOSS_DRAWDOWN = -0.08                 # path drawdown worse than -8 %

# Minimum calendar-day fraction of horizon that must have price bars
_MIN_BAR_FRACTION = 0.5

_BUY_LIKE_ACTIONS = {"STRONG_BUY", "BUY_CANDIDATE"}
_AVOID_LIKE_ACTIONS = {"REDUCE", "SELL", "NO_ACTION"}


# ── Pure computation (synchronous, no DB) ─────────────────────────────────────


def compute_forward_outcome(
    action: str,
    bars: list[MarketPriceBar],
    benchmark_bars: list[MarketPriceBar] | None = None,
    horizon_days: int = 30,
) -> ForwardOutcome:
    """Compute forward outcome from a sorted list of price bars starting at or after
    the recommendation date.

    Parameters
    ----------
    action:
        The recommendation action string (e.g. "BUY_CANDIDATE").
    bars:
        Close-price bars for the target symbol, sorted ascending, starting on or
        after the recommendation date.  Must cover at least ``horizon_days`` calendar days.
    benchmark_bars:
        Same format for the benchmark (e.g. SPY).  Optional.
    horizon_days:
        Calendar days to look forward.

    Returns
    -------
    ForwardOutcome
        Populated dataclass; outcome_status is INSUFFICIENT_DATA when price
        coverage is below the minimum threshold.
    """
    outcome = ForwardOutcome()
    outcome.raw_json["horizon_days"] = horizon_days
    outcome.raw_json["action"] = action

    if not bars:
        outcome.outcome_status = "INSUFFICIENT_DATA"
        outcome.raw_json["reason"] = "no_bars"
        return outcome

    start_bar = bars[0]
    start_price = float(start_bar.adjusted_close or start_bar.close)

    # Collect bars within the horizon window
    horizon_cutoff = start_bar.price_date + dt.timedelta(days=horizon_days)
    window_bars = [b for b in bars if b.price_date <= horizon_cutoff]

    min_needed = max(1, int(horizon_days * _MIN_BAR_FRACTION / 7 * 5))  # approx trading days
    if len(window_bars) < min_needed:
        outcome.outcome_status = "INSUFFICIENT_DATA"
        outcome.raw_json["reason"] = "insufficient_bars"
        outcome.raw_json["bars_found"] = len(window_bars)
        outcome.raw_json["bars_needed"] = min_needed
        return outcome

    end_bar = window_bars[-1]
    end_price = float(end_bar.adjusted_close or end_bar.close)

    outcome.start_price = round(start_price, 4)
    outcome.end_price = round(end_price, 4)
    forward_return = (end_price - start_price) / start_price
    outcome.forward_return_pct = round(forward_return, 6)

    # Max drawdown and runup from start price
    closes = [float(b.adjusted_close or b.close) for b in window_bars]
    peak = start_price
    trough = start_price
    max_drawdown = 0.0
    max_runup = 0.0
    for c in closes:
        if c > peak:
            peak = c
        drawdown = (c - start_price) / start_price
        if drawdown < max_drawdown:
            max_drawdown = drawdown
        runup = (c - start_price) / start_price
        if runup > max_runup:
            max_runup = runup
    _ = trough  # intentionally unused — kept for clarity
    outcome.max_drawdown_pct = round(max_drawdown, 6)
    outcome.max_runup_pct = round(max_runup, 6)

    # Benchmark
    bench_return: float | None = None
    if benchmark_bars:
        bw = [b for b in benchmark_bars if b.price_date <= horizon_cutoff]
        if bw:
            bs = float(bw[0].adjusted_close or bw[0].close)
            be = float(bw[-1].adjusted_close or bw[-1].close)
            bench_return = (be - bs) / bs
            outcome.benchmark_start_price = round(bs, 4)
            outcome.benchmark_end_price = round(be, 4)
            outcome.benchmark_return_pct = round(bench_return, 6)
            outcome.relative_return_pct = round(forward_return - bench_return, 6)

    outcome.outcome_status = "MEASURED"
    outcome.outcome_label = _classify_label(action, forward_return, bench_return, max_drawdown)
    outcome.raw_json["bars_used"] = len(window_bars)
    return outcome


def _classify_label(
    action: str,
    forward_return: float,
    bench_return: float | None,
    max_drawdown: float,
) -> str:
    """Deterministic label from action + returns."""
    rel = forward_return - (bench_return or 0.0)

    if action in _BUY_LIKE_ACTIONS:
        if (
            forward_return >= _BUY_WIN_MIN_FORWARD_RETURN
            or rel >= _BUY_WIN_MIN_RELATIVE_RETURN
        ):
            return "WIN"
        if (
            forward_return <= _BUY_LOSS_MAX_FORWARD_RETURN
            or rel <= _BUY_LOSS_MAX_RELATIVE_RETURN
        ):
            return "LOSS"
        return "NEUTRAL"

    if action == "HOLD":
        if forward_return >= _HOLD_MISSED_UPSIDE_MIN:
            return "MISSED_UPSIDE"
        if forward_return <= _BUY_LOSS_MAX_FORWARD_RETURN:
            return "LOSS"
        return "NEUTRAL"

    if action in _AVOID_LIKE_ACTIONS:
        if forward_return <= _REDUCE_AVOIDED_LOSS_MAX_FORWARD:
            return "AVOIDED_LOSS"
        if forward_return >= _HOLD_MISSED_UPSIDE_MIN:
            return "MISSED_UPSIDE"
        return "NEUTRAL"

    return "UNKNOWN"


# ── Learning event rule engine ────────────────────────────────────────────────


def should_generate_learning_event(outcome: ForwardOutcome, action: str) -> bool:
    """Returns True when outcome warrants a learning event."""
    if outcome.outcome_status != "MEASURED":
        return False
    label = outcome.outcome_label
    if action in _BUY_LIKE_ACTIONS and label == "LOSS":
        return True
    if action == "HOLD" and label == "MISSED_UPSIDE":
        return True
    if action in _AVOID_LIKE_ACTIONS and label == "MISSED_UPSIDE":
        return True
    dd = outcome.max_drawdown_pct
    return bool(dd is not None and dd <= _STOP_LOSS_DRAWDOWN)


def build_learning_event_fields(
    outcome: ForwardOutcome,
    action: str,
    symbol: str,
) -> dict[str, Any]:
    """Build learning event field dict from a measured outcome (no DB required)."""
    label = outcome.outcome_label or "UNKNOWN"
    fwd = outcome.forward_return_pct or 0.0
    rel = outcome.relative_return_pct
    drawdown = outcome.max_drawdown_pct

    if action in _BUY_LIKE_ACTIONS and label == "LOSS":
        event_type = "UNDERPERFORMED_AFTER_BUY"
        severity = "HIGH" if fwd < -0.08 else "MEDIUM"
        title = f"{symbol}: {action} led to {fwd:.1%} loss over horizon"
        summary = (
            f"Recommended {action} for {symbol}. "
            f"Forward return: {fwd:.1%}. "
            + (f"Relative to benchmark: {rel:.1%}. " if rel is not None else "")
            + (f"Max drawdown: {drawdown:.1%}." if drawdown is not None else "")
        )
        causes = ["scoring_overconfident", "missed_risk_factor"]

    elif action == "HOLD" and label == "MISSED_UPSIDE":
        event_type = "MISSED_UPSIDE_AFTER_HOLD"
        severity = "MEDIUM" if fwd < 0.20 else "HIGH"
        title = f"{symbol}: HOLD missed {fwd:.1%} upside"
        summary = (
            f"Held {symbol} but price rose {fwd:.1%} over horizon. "
            + (f"Relative to benchmark: {rel:.1%}." if rel is not None else "")
        )
        causes = ["too_conservative", "missed_catalyst"]

    elif action in _AVOID_LIKE_ACTIONS and label == "MISSED_UPSIDE":
        event_type = "MISSED_UPSIDE_AFTER_HOLD"
        severity = "MEDIUM"
        title = f"{symbol}: {action} missed {fwd:.1%} upside"
        summary = (
            f"Recommended {action} for {symbol} but price rose {fwd:.1%} over horizon."
        )
        causes = ["overly_defensive", "false_negative"]

    elif drawdown is not None and drawdown <= _STOP_LOSS_DRAWDOWN:
        event_type = "STOP_LOSS_LIKE_DRAWDOWN"
        severity = "HIGH"
        title = f"{symbol}: {drawdown:.1%} drawdown after {action}"
        summary = (
            f"Large intra-period drawdown of {drawdown:.1%} after {action} recommendation. "
            "Consider tighter risk gate or stop-loss like condition."
        )
        causes = ["underestimated_volatility", "risk_policy_too_loose"]

    else:
        event_type = "THESIS_BROKEN"
        severity = "LOW"
        title = f"{symbol}: outcome does not match expectation"
        summary = f"{action} for {symbol}. Forward return: {fwd:.1%}."
        causes = []

    return {
        "event_type": event_type,
        "severity": severity,
        "title": title,
        "summary": summary,
        "suspected_causes_json": causes,
        "evidence_json": {
            "forward_return_pct": outcome.forward_return_pct,
            "benchmark_return_pct": outcome.benchmark_return_pct,
            "relative_return_pct": outcome.relative_return_pct,
            "max_drawdown_pct": outcome.max_drawdown_pct,
            "outcome_label": label,
        },
        "suggested_adjustments_json": [
            "Review scoring weights for this symbol/sector.",
            "Inspect news and technical signals at recommendation time.",
        ],
    }


# ── DB-bound async functions ──────────────────────────────────────────────────


async def measure_recommendation_outcome(
    session: AsyncSession,
    recommendation_type: str,
    recommendation_id: uuid.UUID,
    symbol: str,
    action: str,
    score: int | None,
    price_at_recommendation: float | None,
    measured_from: dt.datetime,
    horizon_days: int,
    benchmark_symbol: str = "SPY",
    research_run_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    *,
    _now: dt.datetime | None = None,
) -> Any:
    """Compute + persist a RecommendationOutcome row with horizon-aware idempotency.

    Idempotency rules:
    - MEASURED row  → always returned as-is (final state).
    - PENDING row, horizon not yet elapsed → returned as-is.
    - PENDING row, horizon elapsed → row is updated with computed result.
    - INSUFFICIENT_DATA row, horizon elapsed → row is re-measured (not stale forever).
    - No row, horizon not elapsed → PENDING row is persisted.
    - No row, horizon elapsed → computed result is persisted.

    ``_now`` is injectable for deterministic testing; defaults to ``datetime.now(UTC)``.
    """
    from datetime import UTC

    from db.models import RecommendationOutcome
    from market_data.repository import MarketPriceRepository
    from sqlalchemy import select

    now_utc = _now if _now is not None else dt.datetime.now(UTC)
    horizon_end = measured_from + dt.timedelta(days=horizon_days)
    horizon_elapsed = now_utc >= horizon_end
    measured_to = horizon_end

    repo = MarketPriceRepository(session)

    # Look up existing row
    existing_result = await session.execute(
        select(RecommendationOutcome).where(
            RecommendationOutcome.recommendation_type == recommendation_type,
            RecommendationOutcome.recommendation_id == recommendation_id,
            RecommendationOutcome.horizon_days == horizon_days,
            RecommendationOutcome.benchmark_symbol == benchmark_symbol,
        )
    )
    existing_row = existing_result.scalar_one_or_none()

    # Idempotency: MEASURED is always final
    if existing_row is not None and existing_row.outcome_status == "MEASURED":
        return existing_row

    # Idempotency: PENDING and horizon not yet elapsed — nothing to update
    if existing_row is not None and not horizon_elapsed:
        return existing_row

    # Horizon not elapsed and no row yet — persist PENDING placeholder
    if not horizon_elapsed:
        row = RecommendationOutcome(
            user_id=user_id,
            recommendation_type=recommendation_type,
            recommendation_id=recommendation_id,
            research_run_id=research_run_id,
            symbol=symbol,
            action=action,
            score=score,
            price_at_recommendation=price_at_recommendation,
            measured_from=measured_from,
            measured_to=measured_to,
            horizon_days=horizon_days,
            benchmark_symbol=benchmark_symbol,
            outcome_status="PENDING",
            raw_json={"reason": "horizon_not_elapsed"},
        )
        session.add(row)
        await session.flush()
        await session.refresh(row)
        logger.info(
            "outcome_pending",
            extra={"symbol": symbol, "action": action, "horizon_days": horizon_days},
        )
        return row

    # Horizon has elapsed — compute forward outcome
    start_date = measured_from.date()
    end_date = start_date + dt.timedelta(days=horizon_days + 14)  # buffer for weekends

    bars = await repo.get_bars(symbol, start_date=start_date, end_date=end_date)
    bench_bars = await repo.get_bars(benchmark_symbol, start_date=start_date, end_date=end_date)

    forward = compute_forward_outcome(
        action=action,
        bars=bars,
        benchmark_bars=bench_bars or None,
        horizon_days=horizon_days,
    )

    if existing_row is not None:
        # Update stale PENDING or INSUFFICIENT_DATA row in-place
        existing_row.start_price = forward.start_price
        existing_row.end_price = forward.end_price
        existing_row.benchmark_start_price = forward.benchmark_start_price
        existing_row.benchmark_end_price = forward.benchmark_end_price
        existing_row.forward_return_pct = forward.forward_return_pct
        existing_row.benchmark_return_pct = forward.benchmark_return_pct
        existing_row.relative_return_pct = forward.relative_return_pct
        existing_row.max_drawdown_pct = forward.max_drawdown_pct
        existing_row.max_runup_pct = forward.max_runup_pct
        existing_row.outcome_status = forward.outcome_status
        existing_row.outcome_label = forward.outcome_label
        existing_row.raw_json = forward.raw_json
        await session.flush()
        await session.refresh(existing_row)
        logger.info(
            "outcome_remeasured",
            extra={
                "symbol": symbol,
                "action": action,
                "horizon_days": horizon_days,
                "status": forward.outcome_status,
                "label": forward.outcome_label,
            },
        )
        return existing_row

    # No existing row — create new
    row = RecommendationOutcome(
        user_id=user_id,
        recommendation_type=recommendation_type,
        recommendation_id=recommendation_id,
        research_run_id=research_run_id,
        symbol=symbol,
        action=action,
        score=score,
        price_at_recommendation=price_at_recommendation,
        measured_from=measured_from,
        measured_to=measured_to,
        horizon_days=horizon_days,
        benchmark_symbol=benchmark_symbol,
        start_price=forward.start_price,
        end_price=forward.end_price,
        benchmark_start_price=forward.benchmark_start_price,
        benchmark_end_price=forward.benchmark_end_price,
        forward_return_pct=forward.forward_return_pct,
        benchmark_return_pct=forward.benchmark_return_pct,
        relative_return_pct=forward.relative_return_pct,
        max_drawdown_pct=forward.max_drawdown_pct,
        max_runup_pct=forward.max_runup_pct,
        outcome_status=forward.outcome_status,
        outcome_label=forward.outcome_label,
        raw_json=forward.raw_json,
    )
    session.add(row)
    await session.flush()
    await session.refresh(row)
    logger.info(
        "outcome_measured",
        extra={
            "symbol": symbol,
            "action": action,
            "horizon_days": horizon_days,
            "status": forward.outcome_status,
            "label": forward.outcome_label,
        },
    )
    return row


async def generate_learning_event_from_outcome(
    session: AsyncSession,
    outcome_row: Any,
    action: str,
    symbol: str,
    user_id: uuid.UUID | None,
    research_run_id: uuid.UUID | None = None,
) -> Any | None:
    """Create a LearningEvent for the outcome if it warrants one.

    Returns the created LearningEvent ORM row, or None if no event needed.
    """
    from db.models import LearningEvent

    fwd = ForwardOutcome(
        forward_return_pct=float(outcome_row.forward_return_pct)
        if outcome_row.forward_return_pct is not None
        else None,
        benchmark_return_pct=float(outcome_row.benchmark_return_pct)
        if outcome_row.benchmark_return_pct is not None
        else None,
        relative_return_pct=float(outcome_row.relative_return_pct)
        if outcome_row.relative_return_pct is not None
        else None,
        max_drawdown_pct=float(outcome_row.max_drawdown_pct)
        if outcome_row.max_drawdown_pct is not None
        else None,
        max_runup_pct=float(outcome_row.max_runup_pct)
        if outcome_row.max_runup_pct is not None
        else None,
        outcome_status=outcome_row.outcome_status,
        outcome_label=outcome_row.outcome_label,
    )

    if not should_generate_learning_event(fwd, action):
        return None

    fields = build_learning_event_fields(fwd, action, symbol)
    ev = LearningEvent(
        user_id=user_id,
        recommendation_outcome_id=outcome_row.id,
        research_run_id=research_run_id,
        symbol=symbol,
        status="OPEN",
        **fields,
    )
    session.add(ev)
    await session.flush()
    await session.refresh(ev)
    logger.info(
        "learning_event_created",
        extra={
            "symbol": symbol,
            "event_type": fields["event_type"],
            "severity": fields["severity"],
        },
    )
    return ev


async def measure_latest_recommendations(
    session: AsyncSession,
    user_id: uuid.UUID,
    horizon_days: int = 30,
    benchmark_symbol: str = "SPY",
) -> list[Any]:
    """Measure outcomes for all neutral recs in the user's latest completed run.

    Returns list of RecommendationOutcome rows (may include INSUFFICIENT_DATA rows).
    """
    from db.enums import ResearchRunStatus
    from db.models import NeutralRecommendation, ResearchRun
    from sqlalchemy import select

    # Latest completed run for this user
    latest_run_subq = (
        select(ResearchRun.id)
        .where(
            ResearchRun.user_id == user_id,
            ResearchRun.status == ResearchRunStatus.COMPLETED.value,
        )
        .order_by(ResearchRun.finished_at.desc().nullslast(), ResearchRun.created_at.desc())
        .limit(1)
        .scalar_subquery()
    )

    recs_result = await session.execute(
        select(NeutralRecommendation).where(
            NeutralRecommendation.research_run_id == latest_run_subq
        )
    )
    recs = list(recs_result.scalars().all())

    if not recs:
        return []

    outcomes = []
    for rec in recs:
        outcome_row = await measure_recommendation_outcome(
            session=session,
            recommendation_type="NEUTRAL",
            recommendation_id=rec.id,
            symbol=rec.symbol,
            action=rec.action,
            score=rec.score,
            price_at_recommendation=(
                float(rec.price_at_recommendation)
                if rec.price_at_recommendation is not None
                else None
            ),
            measured_from=rec.as_of_time,
            horizon_days=horizon_days,
            benchmark_symbol=benchmark_symbol,
            research_run_id=rec.research_run_id,
            user_id=user_id,
        )
        outcomes.append(outcome_row)
        # Generate learning event where needed (fire-and-forget, errors non-fatal)
        try:
            await generate_learning_event_from_outcome(
                session=session,
                outcome_row=outcome_row,
                action=rec.action,
                symbol=rec.symbol,
                user_id=user_id,
                research_run_id=rec.research_run_id,
            )
        except Exception as exc:
            logger.warning(
                "learning_event_generation_failed",
                extra={"symbol": rec.symbol, "error": str(exc)},
            )

    return outcomes
