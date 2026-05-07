"""NeutralRecommendation — deterministic scoring engine. No LLM involved."""
from typing import Any

from core.logging import get_logger
from db.enums import RecommendationAction

from research_graph.state import NeutralRecState, ResearchState, ScoreBreakdown

logger = get_logger(__name__)

# ── Score component stubs (filled by later milestones) ─────────────────────
_FUNDAMENTAL_STUB: float = 14.0   # /20 — M4
_VALUATION_STUB: float = 10.0     # /15 — M4
_NEWS_STUB: float = 9.0           # /15 — M8
_PORTFOLIO_FIT_STUB: float = 12.0  # /15 — M9
_STUB_TOTAL: float = _FUNDAMENTAL_STUB + _VALUATION_STUB + _NEWS_STUB + _PORTFOLIO_FIT_STUB


# ── Scoring functions ──────────────────────────────────────────────────────


def _technical_score(signals: dict[str, Any]) -> float:
    """0–20 from RSI, MACD, EMA position, and 1-month momentum."""
    score = 0.0

    # RSI contribution (0–5)
    rsi: float = signals.get("rsi", 50.0)
    if rsi > 70:
        score += 4.0   # overbought — cautious but trending
    elif rsi > 55:
        score += 5.0   # bullish zone
    elif rsi > 45:
        score += 3.0   # neutral
    elif rsi > 30:
        score += 1.5   # bearish
    else:
        score += 0.5   # oversold

    # MACD vs signal line (0–5)
    hist: float = signals.get("macd_histogram", 0.0)
    if hist > 0:
        score += min(5.0, 2.5 + abs(hist) * 1.5)
    else:
        score += max(0.0, 2.5 - abs(hist) * 1.5)

    # Price vs EMA-20 (0–5)
    pve: float = signals.get("price_vs_ema20", 1.0)
    if pve > 1.05:
        score += 5.0
    elif pve > 1.02:
        score += 4.0
    elif pve > 1.0:
        score += 3.0
    elif pve > 0.97:
        score += 2.0
    else:
        score += 0.5

    # 1-month momentum (0–5)
    mom: float = signals.get("momentum_1m", 0.0)
    if mom > 0.10:
        score += 5.0
    elif mom > 0.05:
        score += 4.0
    elif mom > 0.01:
        score += 3.0
    elif mom > -0.03:
        score += 1.5
    else:
        score += 0.0

    return min(20.0, max(0.0, score))


def _risk_score(signals: dict[str, Any]) -> float:
    """0–15. Lower volatility (ATR%) = higher score (more stable = less risky)."""
    atr_pct: float = signals.get("atr_pct", 0.02)
    if atr_pct < 0.010:
        return 15.0
    if atr_pct < 0.015:
        return 13.0
    if atr_pct < 0.020:
        return 11.0
    if atr_pct < 0.030:
        return 9.0
    if atr_pct < 0.040:
        return 6.0
    if atr_pct < 0.060:
        return 4.0
    return 2.0


def score_to_action(score: float, has_position: bool = False) -> RecommendationAction:
    """Lookup table from score to action. Exact spec from CLAUDE.md."""
    if score >= 85:
        return RecommendationAction.STRONG_BUY
    if score >= 70:
        return RecommendationAction.BUY_CANDIDATE
    if score >= 50:
        return RecommendationAction.HOLD
    if score >= 35:
        return RecommendationAction.REDUCE
    if has_position:
        return RecommendationAction.SELL
    return RecommendationAction.NO_ACTION


def _build_reasons(
    action: RecommendationAction, breakdown: ScoreBreakdown
) -> tuple[list[str], list[str]]:
    """Generate human-readable reason strings from score components."""
    reasons: list[str] = []
    risks: list[str] = []

    if breakdown.technical_score >= 15:
        reasons.append("Strong technical momentum: RSI, MACD, and price trend all positive.")
    elif breakdown.technical_score >= 10:
        reasons.append("Moderate technical strength across RSI, MACD, and moving averages.")
    else:
        risks.append("Weak technical signals: below moving averages with bearish momentum.")

    if breakdown.risk_score >= 10:
        reasons.append("Low volatility profile supports a stable entry.")
    else:
        risks.append("Elevated volatility increases position risk.")

    risks.append("Fundamental and valuation scores are placeholder values (M4).")
    return reasons, risks


def neutral_recommendation(state: ResearchState) -> dict[str, Any]:
    """
    Deterministic scoring engine. Produces a NeutralRecState from technical signals.
    No LLM, no randomness. Same inputs always produce same output.
    """
    symbol = state["symbol"]
    signals = state.get("technical_signals") or {}

    try:
        tech = _technical_score(signals)
        risk = _risk_score(signals)
        total = _STUB_TOTAL + tech + risk
        total = round(min(100.0, max(0.0, total)))

        breakdown = ScoreBreakdown(
            technical_score=round(tech, 2),
            fundamental_score=_FUNDAMENTAL_STUB,
            valuation_score=_VALUATION_STUB,
            news_score=_NEWS_STUB,
            portfolio_fit_score=_PORTFOLIO_FIT_STUB,
            risk_score=round(risk, 2),
            total_score=float(total),
        )

        action = score_to_action(float(total))
        confidence = min(1.0, max(0.2, total / 100.0 + 0.10))
        dq = state.get("data_quality_score", 1.0)
        reasons, risks = _build_reasons(action, breakdown)

        rec = NeutralRecState(
            action=action,
            score=int(total),
            confidence=round(confidence, 3),
            final_reason=(
                f"Score {total}/100 ({action.value}). "
                f"Technical: {tech:.0f}/20, Risk: {risk:.0f}/15. "
                f"Fundamental/news/valuation are stubs until M4/M8."
            ),
            score_breakdown=breakdown,
            main_reasons=reasons,
            main_risks=risks,
            data_quality_score=dq,
        )

        logger.info(
            "node_neutral_recommendation",
            symbol=symbol,
            score=total,
            action=action.value,
            confidence=round(confidence, 3),
        )
        return {"neutral_rec": rec, "score_breakdown": breakdown}

    except Exception as exc:
        logger.warning("node_neutral_recommendation_failed", symbol=symbol, error=str(exc))
        return {"errors": [f"neutral_recommendation_failed: {exc}"], "confidence_penalties": [0.30]}
