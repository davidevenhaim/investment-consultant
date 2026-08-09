"""NeutralRecommendation — deterministic scoring engine. LLM is analyst only, not judge."""

from typing import Any

from core.logging import get_logger
from db.enums import RecommendationAction

from research_graph.state import NeutralRecState, ResearchState, ScoreBreakdown

logger = get_logger(__name__)

# Neutral prior /15 when no portfolio account exists; replaced with the real
# portfolio fit score by load_portfolio_context when portfolio data is available.
_PORTFOLIO_FIT_STUB: float = 7.0


# ── Technical score (M4+) ─────────────────────────────────────────────────────


def _technical_score(signals: dict[str, Any]) -> float:
    """0–20 from real technical indicators."""
    score = 0.0
    if (pv200 := signals.get("price_vs_sma_200")) is not None and pv200 > 1.0:
        score += 5.0
    if (pv50 := signals.get("price_vs_sma_50")) is not None and pv50 > 1.0:
        score += 3.0
    if (r3m := signals.get("return_3m")) is not None and r3m > 0:
        score += 3.0
    if (r6m := signals.get("return_6m")) is not None and r6m > 0:
        score += 3.0
    if (rs3m := signals.get("relative_strength_3m_vs_spy")) is not None and rs3m > 0:
        score += 3.0
    rsi = signals.get("rsi_14") or signals.get("rsi")
    if rsi is not None and 45.0 <= rsi <= 70.0:
        score += 2.0
    return min(20.0, max(0.0, score))


# ── Risk score (M4+) ──────────────────────────────────────────────────────────


def _risk_score(signals: dict[str, Any]) -> float:
    """0–15. Lower volatility/drawdown = higher score."""
    score = 0.0
    vol90 = signals.get("volatility_90d")
    if vol90 is None:
        atr = signals.get("atr_14_pct") or signals.get("atr_pct")
        if atr is not None:
            score += (
                6.0
                if atr < 0.010
                else 4.5
                if atr < 0.020
                else 3.0
                if atr < 0.030
                else 1.5
                if atr < 0.050
                else 0.0
            )
    else:
        score += (
            6.0
            if vol90 < 0.15
            else 4.5
            if vol90 < 0.25
            else 3.0
            if vol90 < 0.35
            else 1.5
            if vol90 < 0.50
            else 0.0
        )
    atr_pct = signals.get("atr_14_pct") or signals.get("atr_pct")
    if atr_pct is not None:
        score += (
            4.0
            if atr_pct < 0.010
            else 3.0
            if atr_pct < 0.020
            else 2.0
            if atr_pct < 0.030
            else 1.0
            if atr_pct < 0.050
            else 0.0
        )
    mdd = signals.get("max_drawdown_1y")
    if mdd is not None:
        abs_mdd = abs(mdd)
        score += (
            5.0
            if abs_mdd < 0.10
            else 3.5
            if abs_mdd < 0.20
            else 2.0
            if abs_mdd < 0.30
            else 1.0
            if abs_mdd < 0.45
            else 0.0
        )
    else:
        score += 2.5
    return min(15.0, max(0.0, score))


# ── Fundamental score (M5+) ──────────────────────────────────────────────────


def _fundamental_score(snapshot: Any) -> tuple[float, list[str], list[str]]:
    """0–20 from real company fundamentals. Returns (score, reasons, risks)."""
    if snapshot is None:
        return 0.0, [], ["No fundamental data available."]

    score = 0.0
    reasons: list[str] = []
    risks: list[str] = []

    # Revenue growth (0–4)
    rev_g = snapshot.revenue_growth
    if rev_g is not None:
        if rev_g > 0.20:
            score += 4.0
            reasons.append(f"Strong revenue growth ({rev_g:.0%}).")
        elif rev_g > 0.08:
            score += 3.0
            reasons.append(f"Moderate revenue growth ({rev_g:.0%}).")
        elif rev_g > 0.0:
            score += 1.5
        else:
            risks.append(f"Declining revenue ({rev_g:.0%}).")

    # Earnings growth (0–3)
    earn_g = snapshot.earnings_growth
    if earn_g is not None:
        if earn_g > 0.15:
            score += 3.0
            reasons.append(f"Strong earnings growth ({earn_g:.0%}).")
        elif earn_g > 0.0:
            score += 1.5
        else:
            risks.append(f"Declining earnings ({earn_g:.0%}).")

    # Profit margins (0–4)
    pm = snapshot.profit_margins
    if pm is not None:
        if pm > 0.20:
            score += 4.0
            reasons.append(f"High profit margins ({pm:.0%}).")
        elif pm > 0.10:
            score += 3.0
            reasons.append(f"Good profit margins ({pm:.0%}).")
        elif pm > 0.05:
            score += 2.0
        elif pm > 0.0:
            score += 1.0
        else:
            risks.append(f"Negative or near-zero margins ({pm:.0%}).")

    # Operating margins / gross margins (0–3)
    om = snapshot.operating_margins
    gm = snapshot.gross_margins
    if om is not None and om > 0.15:
        score += 2.0
        reasons.append(f"Strong operating margins ({om:.0%}).")
    elif om is not None and om > 0.05:
        score += 1.0
    if gm is not None and gm > 0.40:
        score += 1.0

    # Return on equity (0–3)
    roe = snapshot.return_on_equity
    if roe is not None:
        if roe > 0.20:
            score += 3.0
            reasons.append(f"High return on equity ({roe:.0%}).")
        elif roe > 0.10:
            score += 2.0
        elif roe > 0.0:
            score += 1.0
        else:
            risks.append(f"Negative ROE ({roe:.0%}).")

    # Balance sheet health (0–3)
    # D/E value is already normalized to ratio by the provider (yfinance: raw/100).
    dte = snapshot.debt_to_equity
    cr = snapshot.current_ratio
    if dte is not None:
        if dte < 0.5:
            score += 2.0
            reasons.append(f"Low debt-to-equity ({dte:.2f}x) — strong balance sheet.")
        elif dte < 1.5:
            score += 1.0
            reasons.append(f"Moderate debt-to-equity ({dte:.2f}x).")
        else:
            risks.append(f"High debt-to-equity ({dte:.2f}x).")
    if cr is not None and cr > 1.5:
        score += 1.0

    return min(20.0, max(0.0, score)), reasons, risks


# ── Valuation score (M5+) ────────────────────────────────────────────────────


def _valuation_score(snapshot: Any) -> tuple[float, list[str], list[str]]:
    """0–15 from real valuation metrics. Growth-adjusted where possible."""
    if snapshot is None:
        return 0.0, [], ["No valuation data available."]

    score = 0.0
    reasons: list[str] = []
    risks: list[str] = []
    rev_g = snapshot.revenue_growth or 0.0
    high_growth = rev_g > 0.20

    # Trailing PE (0–4)
    pe = snapshot.trailing_pe
    if pe is not None and pe > 0:
        pe_ok = 50 if high_growth else 30
        pe_great = 25 if high_growth else 15
        if pe <= pe_great:
            score += 4.0
            reasons.append(f"Attractive trailing P/E ({pe:.1f}).")
        elif pe <= pe_ok:
            score += 2.5
        elif pe <= (70 if high_growth else 45):
            score += 1.0
        else:
            risks.append(f"Expensive trailing P/E ({pe:.1f}).")

    # Forward PE (0–3)
    fpe = snapshot.forward_pe
    if fpe is not None and fpe > 0:
        fpe_ok = 40 if high_growth else 25
        if fpe <= fpe_ok * 0.6:
            score += 3.0
            reasons.append(f"Low forward P/E ({fpe:.1f}) — market pricing in slowdown.")
        elif fpe <= fpe_ok:
            score += 2.0
        elif fpe <= fpe_ok * 1.5:
            score += 1.0
        else:
            risks.append(f"High forward P/E ({fpe:.1f}).")

    # Price-to-Sales (0–3)
    ps = snapshot.price_to_sales
    if ps is not None and ps > 0:
        ps_ok = 10 if high_growth else 4
        if ps <= ps_ok * 0.5:
            score += 3.0
        elif ps <= ps_ok:
            score += 2.0
        elif ps <= ps_ok * 2:
            score += 1.0
        else:
            risks.append(f"High price-to-sales ({ps:.1f}).")

    # Price-to-Book (0–2)
    pb = snapshot.price_to_book
    if pb is not None and pb > 0:
        if pb <= 2.0:
            score += 2.0
            reasons.append(f"Low price-to-book ({pb:.1f}).")
        elif pb <= 5.0:
            score += 1.0
        elif pb > 15.0:
            risks.append(f"Very high price-to-book ({pb:.1f}).")

    # EV/EBITDA (0–3)
    ev_ebitda = snapshot.enterprise_to_ebitda
    if ev_ebitda is not None and ev_ebitda > 0:
        ev_ok = 30 if high_growth else 15
        if ev_ebitda <= ev_ok * 0.6:
            score += 3.0
        elif ev_ebitda <= ev_ok:
            score += 2.0
        elif ev_ebitda <= ev_ok * 1.5:
            score += 1.0
        else:
            risks.append(f"High EV/EBITDA ({ev_ebitda:.1f}).")

    return min(15.0, max(0.0, score)), reasons, risks


# ── Action threshold table ────────────────────────────────────────────────────


def score_to_action(
    score: float,
    has_position: bool = False,
    config: dict[str, Any] | None = None,
) -> RecommendationAction:
    """Lookup table from score to action. Thresholds from strategy config or defaults."""
    thresh = (config or {}).get("action_thresholds", {})
    t_strong_buy = thresh.get("strong_buy", 85)
    t_buy = thresh.get("buy_candidate", 70)
    t_hold = thresh.get("hold", 50)
    t_reduce = thresh.get("reduce", 35)

    if score >= t_strong_buy:
        return RecommendationAction.STRONG_BUY
    if score >= t_buy:
        return RecommendationAction.BUY_CANDIDATE
    if score >= t_hold:
        return RecommendationAction.HOLD
    if score >= t_reduce:
        return RecommendationAction.REDUCE
    if has_position:
        return RecommendationAction.SELL
    return RecommendationAction.NO_ACTION


# ── Analysis completeness ─────────────────────────────────────────────────────


def _build_completeness(
    signals: dict[str, Any] | None,
    fundamentals: Any,
    fundamentals_dq: float,
    market_dq: float,
    news_available: bool = False,
) -> tuple[list[str], list[str], float, str]:
    completed: list[str] = []
    missing: list[str] = ["portfolio_context"]  # load_portfolio_context updates this

    if news_available:
        completed.append("news")
    else:
        missing.append("news")

    if signals:
        completed.extend(["market_data", "technical_signals", "price_risk"])
    else:
        missing.append("market_data")

    if fundamentals is not None and fundamentals_dq >= 0.3:
        completed.extend(["fundamentals", "valuation"])
    elif fundamentals is not None:
        completed.append("fundamentals_partial")
        missing.append("fundamentals_complete")
    else:
        missing.extend(["fundamentals", "valuation"])

    total = len(completed) + len(missing)
    completeness = round(len(completed) / total, 3) if total > 0 else 0.0
    scope = "TECHNICAL_FUNDAMENTAL_VALUATION_RISK_PARTIAL"
    return completed, missing, completeness, scope


# ── Main node ─────────────────────────────────────────────────────────────────


def neutral_recommendation(state: ResearchState) -> dict[str, Any]:
    """
    Deterministic scoring engine.
    Technical + Risk + Fundamental + Valuation + News: real data when available.
    Portfolio fit: neutral prior here; replaced by load_portfolio_context downstream.
    """
    symbol = state["symbol"]
    signals = state.get("technical_signals") or {}
    fundamentals = state.get("fundamentals_snapshot")
    fdq = state.get("fundamentals_data_quality") or 0.0
    market_dq = state.get("data_quality_score") or 1.0
    strategy_config = state.get("strategy_config") or {}
    stub_scores = strategy_config.get("stub_scores", {})
    portfolio_fit_stub = float(stub_scores.get("portfolio_fit", _PORTFOLIO_FIT_STUB))

    # M8: real news score from fetch_news node; fall back to stub if unavailable
    news_score_result: Any = state.get("news_score_result")
    if news_score_result is not None:
        news_score = float(news_score_result.score)
    else:
        from news.scoring import _NO_DATA_SCORE

        news_score = float(stub_scores.get("news", _NO_DATA_SCORE))

    try:
        tech = _technical_score(signals)
        risk = _risk_score(signals)
        fund, fund_reasons, fund_risks = _fundamental_score(fundamentals)
        val, val_reasons, val_risks = _valuation_score(fundamentals)

        raw = tech + risk + fund + val + news_score + portfolio_fit_stub
        total = round(min(100.0, max(0.0, raw)))

        news_available = news_score_result is not None and not news_score_result.no_data
        completed, missing, completeness, scope = _build_completeness(
            signals or None, fundamentals, fdq, market_dq, news_available=news_available
        )

        # Component quality scores
        component_quality: dict[str, float] = {
            "market_data": market_dq,
            "technical_signals": 1.0 if signals else 0.0,
            "fundamentals": fdq,
            "news": 0.0,
            "portfolio_context": 0.0,
        }

        breakdown = ScoreBreakdown(
            technical_score=round(tech, 2),
            fundamental_score=round(fund, 2),
            valuation_score=round(val, 2),
            news_score=round(news_score, 2),
            portfolio_fit_score=portfolio_fit_stub,
            risk_score=round(risk, 2),
            total_score=float(total),
            recommendation_scope=scope,
            analysis_completeness_score=completeness,
            completed_components=completed,
            missing_components=missing,
            component_quality_scores=component_quality,
        )

        action = score_to_action(float(total), config=strategy_config)
        confidence = min(1.0, max(0.2, total / 100.0 + 0.10))
        # Reduce confidence if fundamentals missing
        if fdq < 0.3:
            confidence = min(confidence, 0.70)
        # Apply penalties accumulated by upstream nodes (fetch/signal failures)
        node_penalty = sum(state.get("confidence_penalties") or [])
        if node_penalty > 0:
            confidence = max(0.0, confidence - node_penalty)

        # Build missing_details for final output
        missing_details: list[str] = []
        if news_score_result is None or news_score_result.no_data:
            missing_details.append(
                "News data unavailable. Recent material events may not be reflected."
            )
        missing_details.append(
            "Portfolio context not yet loaded. Personalized view may adjust this recommendation."
        )
        if fdq < 0.3:
            missing_details.append(
                f"Fundamentals data quality is low ({fdq:.0%}). Key metrics may be missing."
            )

        # Combine reasons and risks from all scoring components
        reasons = fund_reasons + val_reasons
        risks = fund_risks + val_risks

        # Add technical/risk narrative
        pv200 = signals.get("price_vs_sma_200")
        r3m = signals.get("return_3m")
        if pv200 is not None and pv200 > 1.0:
            reasons.append(f"Price above SMA200 ({pv200:.2f}x) — long-term uptrend intact.")
        elif pv200 is not None:
            risks.append(f"Price below SMA200 ({pv200:.2f}x) — long-term downtrend.")
        if r3m is not None and r3m > 0:
            reasons.append(f"Positive 3-month momentum (+{r3m:.1%}).")
        elif r3m is not None:
            risks.append(f"Negative 3-month momentum ({r3m:.1%}).")
        risks.append("Portfolio context pending.")

        # ── M7: Apply LLM qualitative output ────────────────────────────────
        llm: Any = state.get("llm_analysis")
        llm_warnings: list[str] = list(state.get("llm_warnings") or [])

        if llm is not None and llm.llm_enabled:
            # Add LLM qualitative reasons (never numeric score/action)
            thesis = llm.thesis
            if thesis.short_thesis:
                reasons.insert(0, f"[LLM thesis] {thesis.short_thesis}")
            reasons.extend([f"[LLM] {p}" for p in thesis.bullish_points[:3]])
            risks.extend([f"[LLM] {r}" for r in llm.risk.key_risks[:3]])
            if llm.critic.strongest_counterargument:
                risks.append(f"[LLM critic] {llm.critic.strongest_counterargument}")

            # Add LLM missing details
            missing_details.extend(llm.missing_details.blocking_missing_details)
            missing_details.extend(llm.missing_details.non_blocking_missing_details)

            # Apply confidence penalty (additive, hard-capped — LLM never raises confidence)
            llm_penalty = llm.total_confidence_penalty
            confidence = round(max(0.0, confidence - llm_penalty), 3)

            # STRONG_BUY cap — only downgrade, never upgrade (clarification point 5)
            cap_applied = False
            if llm.critic.should_cap_strong_buy and action == RecommendationAction.STRONG_BUY:
                action = RecommendationAction.BUY_CANDIDATE
                cap_applied = True

            breakdown = ScoreBreakdown(
                **{
                    **breakdown.model_dump(),
                    "llm_enabled": True,
                    "llm_model": llm.llm_model,
                    "llm_analysis_quality": llm.analysis_quality_score,
                    "llm_confidence_penalty": llm_penalty,
                    "critic_should_cap_strong_buy": cap_applied,
                    "thesis_alignment": thesis.previous_thesis_alignment,
                    "strongest_counterargument": llm.critic.strongest_counterargument,
                    "llm_warnings": llm_warnings,
                },
            )

            news_src = "real" if (news_score_result and not news_score_result.no_data) else "stub"
            final_reason = (
                f"Score {total}/100 ({action.value}). "
                f"Technical: {tech:.0f}/20, Risk: {risk:.0f}/15, "
                f"Fundamental: {fund:.0f}/20, Valuation: {val:.0f}/15, "
                f"News ({news_src}): {news_score:.0f}/15. "
                f"Thesis: {thesis.short_thesis[:120]} "
                f"Previous recommendation: {thesis.previous_thesis_alignment}. "
                f"LLM confidence penalty: -{llm_penalty:.2f}. "
                f"Analysis completeness: {completeness:.0%}."
            )
        else:
            breakdown = ScoreBreakdown(
                **{**breakdown.model_dump(), "llm_enabled": False, "llm_warnings": llm_warnings}
            )
            news_src = "real" if (news_score_result and not news_score_result.no_data) else "stub"
            final_reason = (
                f"Score {total}/100 ({action.value}). "
                f"Technical (real): {tech:.0f}/20, Risk (real): {risk:.0f}/15, "
                f"Fundamental (real): {fund:.0f}/20, Valuation (real): {val:.0f}/15. "
                f"News ({news_src}): {news_score:.0f}/15, "
                f"Portfolio stub: {portfolio_fit_stub:.0f}/15. "
                f"Analysis completeness: {completeness:.0%}."
            )

        rec = NeutralRecState(
            action=action,
            score=int(total),
            confidence=round(confidence, 3),
            final_reason=final_reason,
            score_breakdown=breakdown,
            main_reasons=reasons,
            main_risks=risks,
            missing_details=missing_details,
            data_quality_score=market_dq,
        )

        logger.info(
            "node_neutral_recommendation",
            symbol=symbol,
            score=total,
            action=action.value,
            tech=tech,
            risk=risk,
            fund=fund,
            val=val,
            completeness=completeness,
            node_confidence_penalty=round(node_penalty, 3),
            confidence=round(confidence, 3),
        )
        return {
            "neutral_rec": rec,
            "score_breakdown": breakdown,
            "analysis_completeness": completeness,
            "completed_components": completed,
            "missing_components": missing,
        }

    except Exception as exc:
        logger.warning("node_neutral_recommendation_failed", symbol=symbol, error=str(exc))
        return {
            "errors": [f"neutral_recommendation_failed: {exc}"],
            "confidence_penalties": [0.30],
        }
