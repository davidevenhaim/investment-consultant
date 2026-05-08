"""NeutralRecommendation — deterministic scoring engine. No LLM involved."""
from typing import Any

from core.logging import get_logger
from db.enums import RecommendationAction

from research_graph.state import NeutralRecState, ResearchState, ScoreBreakdown

logger = get_logger(__name__)

# ── Score component stubs (filled by later milestones) ─────────────────────
_FUNDAMENTAL_STUB: float = 14.0   # /20 — M5+
_VALUATION_STUB: float = 10.0     # /15 — M5+
_NEWS_STUB: float = 9.0           # /15 — M8
_PORTFOLIO_FIT_STUB: float = 12.0  # /15 — M9
_STUB_TOTAL: float = _FUNDAMENTAL_STUB + _VALUATION_STUB + _NEWS_STUB + _PORTFOLIO_FIT_STUB


def _technical_score(signals: dict[str, Any]) -> float:
    """0–20 from real technical indicators (M4+)."""
    score = 0.0

    # Price vs SMA200 (+5): strongest trend filter
    pv200 = signals.get("price_vs_sma_200")
    if pv200 is not None and pv200 > 1.0:
        score += 5.0

    # Price vs SMA50 (+3)
    pv50 = signals.get("price_vs_sma_50")
    if pv50 is not None and pv50 > 1.0:
        score += 3.0

    # 3-month return positive (+3)
    r3m = signals.get("return_3m")
    if r3m is not None and r3m > 0:
        score += 3.0

    # 6-month return positive (+3)
    r6m = signals.get("return_6m")
    if r6m is not None and r6m > 0:
        score += 3.0

    # Relative strength 3M vs SPY (+3)
    rs3m = signals.get("relative_strength_3m_vs_spy")
    if rs3m is not None and rs3m > 0:
        score += 3.0

    # RSI in healthy zone 45–70 (+2)
    rsi = signals.get("rsi_14")
    if rsi is not None and 45.0 <= rsi <= 70.0:
        score += 2.0

    # Fallback: legacy rsi key from M3 tests
    elif rsi is None:
        rsi_legacy = signals.get("rsi")
        if rsi_legacy is not None and 45.0 <= rsi_legacy <= 70.0:
            score += 2.0

    return min(20.0, max(0.0, score))


def _risk_score(signals: dict[str, Any]) -> float:
    """0–15. Lower volatility/drawdown = higher score."""
    score = 0.0

    # 90-day annualized volatility (0–6)
    vol90 = signals.get("volatility_90d")
    if vol90 is None:
        # fallback to M3 atr_pct
        atr = signals.get("atr_pct") or signals.get("atr_14_pct")
        if atr is not None:
            if atr < 0.010:
                score += 6.0
            elif atr < 0.020:
                score += 4.5
            elif atr < 0.030:
                score += 3.0
            elif atr < 0.050:
                score += 1.5
            else:
                score += 0.0
    else:
        if vol90 < 0.15:
            score += 6.0
        elif vol90 < 0.25:
            score += 4.5
        elif vol90 < 0.35:
            score += 3.0
        elif vol90 < 0.50:
            score += 1.5
        else:
            score += 0.0

    # ATR% (0–4)
    atr_pct_val = signals.get("atr_14_pct") or signals.get("atr_pct")
    if atr_pct_val is not None:
        if atr_pct_val < 0.010:
            score += 4.0
        elif atr_pct_val < 0.020:
            score += 3.0
        elif atr_pct_val < 0.030:
            score += 2.0
        elif atr_pct_val < 0.050:
            score += 1.0
        else:
            score += 0.0

    # Max drawdown 1Y (0–5)
    mdd = signals.get("max_drawdown_1y")
    if mdd is not None:
        abs_mdd = abs(mdd)
        if abs_mdd < 0.10:
            score += 5.0
        elif abs_mdd < 0.20:
            score += 3.5
        elif abs_mdd < 0.30:
            score += 2.0
        elif abs_mdd < 0.45:
            score += 1.0
        else:
            score += 0.0
    else:
        score += 2.5  # neutral stub if missing

    return min(15.0, max(0.0, score))


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
    action: RecommendationAction, breakdown: ScoreBreakdown, signals: dict[str, Any]
) -> tuple[list[str], list[str]]:
    reasons: list[str] = []
    risks: list[str] = []

    pv200 = signals.get("price_vs_sma_200")
    r3m = signals.get("return_3m")
    rs3m = signals.get("relative_strength_3m_vs_spy")

    if pv200 is not None and pv200 > 1.0:
        reasons.append(f"Price above SMA200 ({pv200:.2f}x) — long-term uptrend intact.")
    elif pv200 is not None:
        risks.append(f"Price below SMA200 ({pv200:.2f}x) — long-term downtrend.")

    if r3m is not None and r3m > 0:
        reasons.append(f"Positive 3-month momentum (+{r3m:.1%}).")
    elif r3m is not None:
        risks.append(f"Negative 3-month momentum ({r3m:.1%}).")

    if rs3m is not None and rs3m > 0:
        reasons.append(f"Outperforming SPY over 3 months by {rs3m:.1%}.")
    elif rs3m is not None:
        risks.append(f"Underperforming SPY over 3 months by {abs(rs3m):.1%}.")

    vol90 = signals.get("volatility_90d")
    if vol90 is not None:
        if vol90 > 0.40:
            risks.append(f"High 90-day volatility ({vol90:.0%} annualized).")
        else:
            reasons.append(f"Moderate volatility ({vol90:.0%} annualized).")

    risks.append("Fundamental and valuation scores are placeholder values (M5+).")
    return reasons, risks


def neutral_recommendation(state: ResearchState) -> dict[str, Any]:
    """
    Deterministic scoring engine. Uses real technical/risk signals (M4).
    Fundamental/news/valuation remain stubs.
    """
    symbol = state["symbol"]
    signals = state.get("technical_signals") or {}

    try:
        tech = _technical_score(signals)
        risk = _risk_score(signals)
        total = round(min(100.0, max(0.0, _STUB_TOTAL + tech + risk)))

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
        reasons, risks = _build_reasons(action, breakdown, signals)

        rec = NeutralRecState(
            action=action,
            score=int(total),
            confidence=round(confidence, 3),
            final_reason=(
                f"Score {total}/100 ({action.value}). "
                f"Technical (real M4 data): {tech:.0f}/20, "
                f"Risk (real M4 data): {risk:.0f}/15. "
                f"Fundamental/news/valuation stubs until M5/M8."
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
            tech=tech,
            risk=risk,
        )
        return {"neutral_rec": rec, "score_breakdown": breakdown}

    except Exception as exc:
        logger.warning("node_neutral_recommendation_failed", symbol=symbol, error=str(exc))
        return {
            "errors": [f"neutral_recommendation_failed: {exc}"],
            "confidence_penalties": [0.30],
        }
