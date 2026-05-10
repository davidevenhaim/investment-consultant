"""Prompt builder — formats research context into the LLM prompt template."""
from typing import Any

_MAX_MEMORY_CHARS = 500  # per memory entry
_MAX_NEWS_TITLE_CHARS = 120
_MAX_NEWS_DESC_CHARS = 200
_MAX_NEWS_ARTICLES = 5


def _fmt_pct(v: float | None) -> str:
    return f"{v:.1%}" if v is not None else "N/A"


def _fmt_float(v: float | None, decimals: int = 2) -> str:
    return f"{v:.{decimals}f}" if v is not None else "N/A"


def _fmt_price(v: float | None) -> str:
    return f"${v:.2f}" if v is not None else "N/A"


def build_context(state: dict[str, Any]) -> str:
    """
    Build a structured context string from ResearchState for injection into prompt.
    Stays under ~3000 tokens. All values from state — never invented.
    """
    symbol = state.get("symbol", "UNKNOWN")
    signals: dict[str, Any] = state.get("technical_signals") or {}
    fundamentals: Any = state.get("fundamentals_snapshot")
    memory_ctx: Any = state.get("memory_context")

    price = signals.get("latest_close")
    as_of = str(state.get("as_of_time", ""))[:10]

    lines: list[str] = [
        f"Symbol: {symbol}",
        f"Current price: {_fmt_price(price)}",
        f"As of: {as_of}",
        "",
        "=== Technical Signals ===",
    ]

    if signals:
        lines += [
            f"RSI-14: {_fmt_float(signals.get('rsi_14'), 1)}",
            f"Price vs SMA200: {_fmt_pct(signals.get('price_vs_sma_200', 1.0) - 1.0)}"
            if signals.get("price_vs_sma_200") is not None else "Price vs SMA200: N/A",
            f"Price vs SMA50: {_fmt_pct(signals.get('price_vs_sma_50', 1.0) - 1.0)}"
            if signals.get("price_vs_sma_50") is not None else "Price vs SMA50: N/A",
            f"3M return: {_fmt_pct(signals.get('return_3m'))}",
            f"6M return: {_fmt_pct(signals.get('return_6m'))}",
            f"3M vs SPY: {_fmt_pct(signals.get('relative_strength_3m_vs_spy'))}",
            f"Volatility (90d annualized): {_fmt_pct(signals.get('volatility_90d'))}",
        ]
    else:
        lines.append("No technical signals available.")

    lines += ["", "=== Fundamentals ==="]

    if fundamentals is not None:
        # D/E is already normalized by provider (ratio form). Always display ratio.
        dte = fundamentals.debt_to_equity
        dte_str = f"{dte:.3f}x (normalized ratio)" if dte is not None else "N/A"
        lines += [
            f"Revenue growth: {_fmt_pct(fundamentals.revenue_growth)}",
            f"Earnings growth: {_fmt_pct(fundamentals.earnings_growth)}",
            f"Profit margins: {_fmt_pct(fundamentals.profit_margins)}",
            f"Operating margins: {_fmt_pct(fundamentals.operating_margins)}",
            f"ROE: {_fmt_pct(fundamentals.return_on_equity)}",
            f"Trailing PE: {_fmt_float(fundamentals.trailing_pe, 1)}",
            f"Forward PE: {_fmt_float(fundamentals.forward_pe, 1)}",
            f"Price/Book: {_fmt_float(fundamentals.price_to_book, 1)}",
            f"Price/Sales: {_fmt_float(fundamentals.price_to_sales, 1)}",
            f"EV/EBITDA: {_fmt_float(fundamentals.enterprise_to_ebitda, 1)}",
            f"Debt-to-equity: {dte_str}",
            f"Current ratio: {_fmt_float(fundamentals.current_ratio, 2)}",
            f"Completeness: {fundamentals.completeness_score:.0%}",
        ]
    else:
        lines.append("Fundamental data not available.")

    # Score breakdown
    score_bd: Any = state.get("score_breakdown")
    if score_bd is not None:
        lines += [
            "",
            "=== Deterministic Score Breakdown (do NOT change these numbers) ===",
            f"Technical: {score_bd.technical_score:.0f}/20",
            f"Risk: {score_bd.risk_score:.0f}/15",
            f"Fundamental: {score_bd.fundamental_score:.0f}/20",
            f"Valuation: {score_bd.valuation_score:.0f}/15",
            f"Total: {score_bd.total_score:.0f}/100",
        ]

    # Previous memory
    lines += ["", "=== Previous Research Memory ==="]
    if memory_ctx is not None and memory_ctx.memory_count > 0:
        prev_rec = memory_ctx.previous_recommendation or {}
        if prev_rec:
            lines += [
                f"Last recommendation: {prev_rec.get('action', 'N/A')}, "
                f"score {prev_rec.get('score', 'N/A')}, "
                f"price {_fmt_price(prev_rec.get('price_at_recommendation'))}, "
                f"date {str(prev_rec.get('as_of_time', ''))[:10]}",
            ]
        for i, mem in enumerate(memory_ctx.relevant_memories[:2]):
            excerpt = (mem.content or "")[:_MAX_MEMORY_CHARS]
            if len(mem.content or "") > _MAX_MEMORY_CHARS:
                excerpt += " [truncated]"
            lines += [f"Memory {i + 1}: {excerpt}"]
    else:
        lines.append("No previous research found for this symbol. First run.")

    # News items (M8+)
    lines += ["", "=== Recent News ==="]
    news_score_result: Any = state.get("news_score_result")
    news_items: list[dict[str, Any]] = state.get("news_items") or []
    if news_items:
        top_articles = news_items[:_MAX_NEWS_ARTICLES]
        for i, art in enumerate(top_articles, 1):
            title = str(art.get("title") or "")[:_MAX_NEWS_TITLE_CHARS]
            source = art.get("source_name") or "Unknown"
            pub_date = str(art.get("published_at") or "")[:10]
            desc = str(art.get("description") or "")[:_MAX_NEWS_DESC_CHARS]
            sentiment = art.get("sentiment_score", 0.0)
            lines.append(
                f"Article {i}: [{source}] {pub_date} — {title}"
                + (f" | {desc}" if desc else "")
                + f" (sentiment: {sentiment:+.2f})"
            )
        if news_score_result is not None:
            lines.append(
                f"News score: {news_score_result.score:.1f}/15 — {news_score_result.reason}"
            )
    else:
        lines.append("No news data available.")

    # ── M9.5: trading history context ────────────────────────────────────────
    symbol_trading_stats: dict[str, Any] | None = state.get("symbol_trading_stats")
    behavioral_flags: list[str] = state.get("behavioral_flags") or []
    if symbol_trading_stats:
        lines.append("")
        lines.append(f"=== Historical Trading Profile for {symbol} ===")
        wr = symbol_trading_stats.get("win_rate")
        lines.append(f"Win rate: {wr:.1%}" if wr is not None else "Win rate: N/A")
        aw = symbol_trading_stats.get("avg_winner_pct")
        al = symbol_trading_stats.get("avg_loser_pct")
        if aw is not None:
            lines.append(f"Avg winner: +{aw:.1%}")
        if al is not None:
            lines.append(f"Avg loser: {al:.1%}")
        hd = symbol_trading_stats.get("avg_holding_days")
        if hd is not None:
            lines.append(f"Avg holding period: {hd:.0f} days")
        ct = symbol_trading_stats.get("completed_trades")
        if ct is not None:
            lines.append(f"Completed trades: {ct}")
        if behavioral_flags:
            lines.append(f"Behavioral flags: {', '.join(behavioral_flags)}")

    lines += [
        "",
        "=== Data Gaps (do not speculate about these) ===",
        "SEC filings: NOT AVAILABLE (M17 pending)",
    ]

    return "\n".join(lines)


def format_prompt(template: str, symbol: str, context: str) -> str:
    """
    Substitute {{SYMBOL}} and {{CONTEXT}} placeholders in the template.
    Uses explicit replacement to avoid str.format() conflicts with JSON curly braces.
    """
    return template.replace("{{SYMBOL}}", symbol).replace("{{CONTEXT}}", context)
