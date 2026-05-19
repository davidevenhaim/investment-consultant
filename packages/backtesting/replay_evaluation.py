"""Pure helpers for M12.8 Replay Evaluation.

No DB access, no LLM calls, no external I/O.
Accepts plain dicts from:
  - replay report timelines (output of build_timeline_summary / build_timeline_changes)
  - backtest run fields (initial_cash, final_equity, etc.)
  - backtest summary_json (trade_breakdown, skip_breakdown, open/closed_positions, ...)
  - backtest trade list (as plain dicts with symbol/trade_type/reason/etc.)
"""

from __future__ import annotations

from typing import Any

_BUY_TRADE_TYPES: frozenset[str] = frozenset({"BUY", "ADD"})
_SELL_TRADE_TYPES: frozenset[str] = frozenset({"SELL", "REDUCE"})


def _maybe_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


# ── Portfolio result ───────────────────────────────────────────────────────────


def build_portfolio_result(
    run_fields: dict[str, Any],
    summary_json: dict[str, Any],
) -> dict[str, Any]:
    """Build portfolio_result from backtest run fields + summary_json."""
    return {
        "initial_cash": float(run_fields.get("initial_cash") or 0),
        "final_equity": _maybe_float(run_fields.get("final_equity")),
        "total_return_pct": _maybe_float(run_fields.get("total_return_pct")),
        "benchmark_symbol": run_fields.get("benchmark_symbol"),
        "benchmark_return_pct": _maybe_float(run_fields.get("benchmark_return_pct")),
        "relative_return_pct": _maybe_float(run_fields.get("relative_return_pct")),
        "max_drawdown_pct": _maybe_float(run_fields.get("max_drawdown_pct")),
        "total_trades": int(run_fields.get("total_trades") or 0),
        "winning_trades": int(run_fields.get("winning_trades") or 0),
        "losing_trades": int(run_fields.get("losing_trades") or 0),
        "trade_breakdown": dict(summary_json.get("trade_breakdown") or {}),
        "skip_breakdown": dict(summary_json.get("skip_breakdown") or {}),
        "recommendations_considered": int(summary_json.get("recommendations_considered") or 0),
    }


# ── Per-symbol helpers ─────────────────────────────────────────────────────────


def _trades_for_symbol(symbol: str, trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in trades if (t.get("symbol") or "").upper() == symbol.upper()]


def _closed_for_symbol(symbol: str, closed_positions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [p for p in closed_positions if (p.get("symbol") or "").upper() == symbol.upper()]


def _open_for_symbol(symbol: str, open_positions: list[dict[str, Any]]) -> dict[str, Any] | None:
    for p in open_positions:
        if (p.get("symbol") or "").upper() == symbol.upper():
            return p
    return None


# ── Advisor behavior flags ─────────────────────────────────────────────────────


def build_advisor_behavior(
    symbol_trades: list[dict[str, Any]],
    timeline_summary: dict[str, Any],
) -> dict[str, Any]:
    """Compute heuristic behavior flags for one symbol."""
    actual = [t for t in symbol_trades if t.get("trade_type") != "SKIP"]

    reduced_or_exited = any(t.get("trade_type") in _SELL_TRADE_TYPES for t in actual)
    buy_or_add = any(t.get("trade_type") in _BUY_TRADE_TYPES for t in actual)
    only_held = not buy_or_add and not reduced_or_exited

    score_change = timeline_summary.get("score_change")
    score_trending_down = score_change is not None and int(score_change) < 0
    score_improved_meaningfully = score_change is not None and int(score_change) >= 10

    return {
        "reduced_or_exited": reduced_or_exited,
        "buy_or_add": buy_or_add,
        "only_held": only_held,
        "avoided_drawdown_candidate": reduced_or_exited and score_trending_down,
        "missed_upside_candidate": not buy_or_add and score_improved_meaningfully,
    }


# ── Symbol evaluation ──────────────────────────────────────────────────────────


def build_symbol_evaluation(
    symbol: str,
    timeline_summary: dict[str, Any],
    symbol_trades: list[dict[str, Any]],
    closed_positions_for_symbol: list[dict[str, Any]],
    open_position: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build one symbol_evaluation entry."""
    trade_count = sum(1 for t in symbol_trades if t.get("trade_type") != "SKIP")
    skip_count = sum(1 for t in symbol_trades if t.get("trade_type") == "SKIP")

    trade_types: dict[str, int] = {}
    skip_reasons: dict[str, int] = {}
    for t in symbol_trades:
        tt = t.get("trade_type") or "UNKNOWN"
        trade_types[tt] = trade_types.get(tt, 0) + 1
        if tt == "SKIP":
            reason = str(t.get("reason") or "unknown")
            skip_reasons[reason] = skip_reasons.get(reason, 0) + 1

    pnls = [
        float(p["realized_pnl"])
        for p in closed_positions_for_symbol
        if p.get("realized_pnl") is not None
    ]
    realized_pnl: float | None = round(sum(pnls), 4) if pnls else None
    closed_position = closed_positions_for_symbol[-1] if closed_positions_for_symbol else None

    return {
        "symbol": symbol,
        "point_count": timeline_summary.get("point_count"),
        "first_action": timeline_summary.get("first_action"),
        "last_action": timeline_summary.get("last_action"),
        "action_changed": timeline_summary.get("action_changed"),
        "score_change": timeline_summary.get("score_change"),
        "max_score": timeline_summary.get("max_score"),
        "min_score": timeline_summary.get("min_score"),
        "largest_score_move": timeline_summary.get("largest_score_move"),
        "trade_count": trade_count,
        "skip_count": skip_count,
        "trade_types": trade_types,
        "skip_reasons": skip_reasons,
        "realized_pnl": realized_pnl,
        "open_position": open_position,
        "closed_position": closed_position,
        "advisor_behavior": build_advisor_behavior(symbol_trades, timeline_summary),
    }


# ── Highlights ─────────────────────────────────────────────────────────────────


def build_highlights(
    symbol_evaluations: list[dict[str, Any]],
    timelines: list[dict[str, Any]],
    skip_breakdown: dict[str, int],
) -> dict[str, Any]:
    """Build highlight summary across all symbols."""
    empty: dict[str, Any] = {
        "best_symbol": None,
        "worst_symbol": None,
        "most_active_symbol": None,
        "largest_score_drop": None,
        "largest_score_jump": None,
        "most_common_skip_reason": None,
    }
    if not symbol_evaluations:
        return empty

    # best / worst: prefer realized_pnl, fall back to score_change
    best_symbol: str | None = None
    worst_symbol: str | None = None
    evals_with_pnl = [e for e in symbol_evaluations if e.get("realized_pnl") is not None]
    if evals_with_pnl:
        best_symbol = max(evals_with_pnl, key=lambda e: float(e["realized_pnl"]))["symbol"]
        worst_symbol = min(evals_with_pnl, key=lambda e: float(e["realized_pnl"]))["symbol"]
    else:
        evals_with_score = [e for e in symbol_evaluations if e.get("score_change") is not None]
        if evals_with_score:
            best_symbol = max(evals_with_score, key=lambda e: int(e["score_change"]))["symbol"]
            worst_symbol = min(evals_with_score, key=lambda e: int(e["score_change"]))["symbol"]

    # most active by total interaction count
    most_active_symbol: str | None = max(
        symbol_evaluations,
        key=lambda e: (e.get("trade_count") or 0) + (e.get("skip_count") or 0),
    )["symbol"]

    # largest score drop / jump scanning all step-level changes in every timeline
    largest_score_drop: dict[str, Any] | None = None
    largest_score_jump: dict[str, Any] | None = None
    for tl in timelines:
        sym = tl["symbol"]
        for change in tl.get("changes", []):
            delta = change.get("neutral_score_delta")
            if delta is None:
                continue
            delta_int = int(delta)
            new_entry = {
                "symbol": sym,
                "from_as_of_date": change["from_as_of_date"],
                "to_as_of_date": change["to_as_of_date"],
                "delta": delta_int,
            }
            if delta_int < 0 and (
                largest_score_drop is None or delta_int < int(largest_score_drop["delta"])
            ):
                largest_score_drop = new_entry
            elif delta_int > 0 and (
                largest_score_jump is None or delta_int > int(largest_score_jump["delta"])
            ):
                largest_score_jump = new_entry

    most_common_skip_reason: str | None = (
        max(skip_breakdown, key=lambda k: skip_breakdown[k]) if skip_breakdown else None
    )

    return {
        "best_symbol": best_symbol,
        "worst_symbol": worst_symbol,
        "most_active_symbol": most_active_symbol,
        "largest_score_drop": largest_score_drop,
        "largest_score_jump": largest_score_jump,
        "most_common_skip_reason": most_common_skip_reason,
    }


# ── Top-level assembler ────────────────────────────────────────────────────────


def build_evaluation(
    replay_batch_id: str,
    date_range: dict[str, str],
    symbols: list[str],
    run_counts: dict[str, int],
    timelines: list[dict[str, Any]],
    backtest_run_id: str,
    backtest_run_fields: dict[str, Any],
    backtest_summary_json: dict[str, Any],
    backtest_trades: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the full evaluation object. Pure: no DB, no I/O."""
    portfolio_result = build_portfolio_result(backtest_run_fields, backtest_summary_json)

    open_positions: list[dict[str, Any]] = list(backtest_summary_json.get("open_positions") or [])
    closed_positions: list[dict[str, Any]] = list(
        backtest_summary_json.get("closed_positions") or []
    )
    skip_breakdown: dict[str, int] = dict(backtest_summary_json.get("skip_breakdown") or {})

    symbol_evaluations: list[dict[str, Any]] = []
    for tl in timelines:
        sym = tl["symbol"]
        sym_trades = _trades_for_symbol(sym, backtest_trades)
        sym_closed = _closed_for_symbol(sym, closed_positions)
        sym_open = _open_for_symbol(sym, open_positions)
        symbol_evaluations.append(
            build_symbol_evaluation(
                sym,
                tl.get("summary") or {},
                sym_trades,
                sym_closed,
                sym_open,
            )
        )

    highlights = build_highlights(symbol_evaluations, timelines, skip_breakdown)

    return {
        "replay_batch_id": replay_batch_id,
        "backtest_run_id": backtest_run_id,
        "date_range": date_range,
        "symbols": symbols,
        "run_counts": run_counts,
        "portfolio_result": portfolio_result,
        "symbol_evaluations": symbol_evaluations,
        "highlights": highlights,
    }
