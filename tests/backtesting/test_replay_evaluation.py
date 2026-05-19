"""Unit tests for packages/backtesting/replay_evaluation.py (M12.8).

All tests are pure — no DB, no I/O.
"""

from __future__ import annotations

from typing import Any

import pytest
from backtesting.replay_evaluation import (
    build_advisor_behavior,
    build_evaluation,
    build_highlights,
    build_portfolio_result,
    build_symbol_evaluation,
)

# ── Fixtures / factories ───────────────────────────────────────────────────────


def _run_fields(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "initial_cash": 10000.0,
        "final_equity": 10500.0,
        "total_return_pct": 0.05,
        "benchmark_symbol": "SPY",
        "benchmark_return_pct": 0.02,
        "relative_return_pct": 0.03,
        "max_drawdown_pct": 0.01,
        "total_trades": 2,
        "winning_trades": 1,
        "losing_trades": 0,
    }
    base.update(overrides)
    return base


def _summary_json(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "trade_breakdown": {"BUY": 1, "SELL": 1, "SKIP": 3},
        "skip_breakdown": {"no_position_to_reduce": 2, "insufficient_cash": 1},
        "recommendations_considered": 5,
        "open_positions": [],
        "closed_positions": [],
    }
    base.update(overrides)
    return base


def _timeline_summary(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "point_count": 4,
        "first_action": "HOLD",
        "last_action": "BUY_CANDIDATE",
        "action_changed": True,
        "score_change": 12,
        "max_score": 72,
        "min_score": 60,
        "largest_score_move": {
            "from_as_of_date": "2025-01-08",
            "to_as_of_date": "2025-01-15",
            "delta": 12,
        },
    }
    base.update(overrides)
    return base


def _trade(symbol: str, trade_type: str, reason: str | None = None) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "action": "HOLD",
        "trade_type": trade_type,
        "reason": reason,
        "quantity": 10.0,
        "price": 100.0,
        "cash_delta": None,
        "raw_json": {},
    }


def _timeline(
    symbol: str,
    changes: list[dict[str, Any]] | None = None,
    summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "symbol": symbol,
        "points": [],
        "summary": summary or _timeline_summary(),
        "changes": changes or [],
    }


def _change(from_date: str, to_date: str, delta: int) -> dict[str, Any]:
    return {
        "from_as_of_date": from_date,
        "to_as_of_date": to_date,
        "action_changed": False,
        "neutral_action_from": "HOLD",
        "neutral_action_to": "HOLD",
        "neutral_score_delta": delta,
        "changed_components": [],
        "explanation": "test",
    }


# ── build_portfolio_result ─────────────────────────────────────────────────────


def test_portfolio_result_maps_run_fields() -> None:
    rf = _run_fields()
    sj = _summary_json()
    result = build_portfolio_result(rf, sj)

    assert result["initial_cash"] == 10000.0
    assert result["final_equity"] == 10500.0
    assert result["total_return_pct"] == pytest.approx(0.05)
    assert result["benchmark_symbol"] == "SPY"
    assert result["total_trades"] == 2
    assert result["winning_trades"] == 1
    assert result["losing_trades"] == 0


def test_portfolio_result_includes_breakdowns() -> None:
    sj = _summary_json()
    result = build_portfolio_result(_run_fields(), sj)

    assert result["trade_breakdown"] == {"BUY": 1, "SELL": 1, "SKIP": 3}
    assert result["skip_breakdown"] == {"no_position_to_reduce": 2, "insufficient_cash": 1}
    assert result["recommendations_considered"] == 5


def test_portfolio_result_handles_none_fields() -> None:
    rf = _run_fields(final_equity=None, benchmark_return_pct=None)
    result = build_portfolio_result(rf, _summary_json())

    assert result["final_equity"] is None
    assert result["benchmark_return_pct"] is None


# ── build_advisor_behavior ─────────────────────────────────────────────────────


def test_advisor_behavior_buy_detected() -> None:
    trades = [_trade("AAPL", "BUY"), _trade("AAPL", "SKIP", "no_signal")]
    behavior = build_advisor_behavior(trades, _timeline_summary(score_change=5))

    assert behavior["buy_or_add"] is True
    assert behavior["reduced_or_exited"] is False
    assert behavior["only_held"] is False


def test_advisor_behavior_reduce_detected() -> None:
    trades = [_trade("TSLA", "REDUCE"), _trade("TSLA", "SKIP")]
    behavior = build_advisor_behavior(trades, _timeline_summary(score_change=-8))

    assert behavior["reduced_or_exited"] is True
    assert behavior["buy_or_add"] is False
    assert behavior["avoided_drawdown_candidate"] is True  # reduced AND score trending down


def test_advisor_behavior_only_held_all_skips() -> None:
    trades = [_trade("AAPL", "SKIP"), _trade("AAPL", "SKIP")]
    behavior = build_advisor_behavior(trades, _timeline_summary(score_change=3))

    assert behavior["only_held"] is True
    assert behavior["buy_or_add"] is False
    assert behavior["reduced_or_exited"] is False


def test_advisor_behavior_missed_upside_candidate() -> None:
    trades = [_trade("NVDA", "SKIP")] * 3
    behavior = build_advisor_behavior(trades, _timeline_summary(score_change=15))

    assert behavior["missed_upside_candidate"] is True  # never bought + score improved >= 10


def test_advisor_behavior_not_missed_upside_small_gain() -> None:
    trades = [_trade("NVDA", "SKIP")]
    behavior = build_advisor_behavior(trades, _timeline_summary(score_change=5))

    assert behavior["missed_upside_candidate"] is False  # < 10 threshold


def test_advisor_behavior_no_trades_no_score_change() -> None:
    behavior = build_advisor_behavior([], _timeline_summary(score_change=None))

    assert behavior["avoided_drawdown_candidate"] is False
    assert behavior["missed_upside_candidate"] is False


# ── build_symbol_evaluation ────────────────────────────────────────────────────


def test_symbol_evaluation_trade_count() -> None:
    trades = [
        _trade("AAPL", "BUY"),
        _trade("AAPL", "SKIP", "no_signal"),
        _trade("AAPL", "SKIP", "no_signal"),
    ]
    ev = build_symbol_evaluation("AAPL", _timeline_summary(), trades, [], None)

    assert ev["trade_count"] == 1
    assert ev["skip_count"] == 2


def test_symbol_evaluation_trade_types_breakdown() -> None:
    trades = [
        _trade("TSLA", "REDUCE"),
        _trade("TSLA", "SELL"),
        _trade("TSLA", "SKIP", "no_position_to_reduce"),
        _trade("TSLA", "SKIP", "no_position_to_reduce"),
        _trade("TSLA", "SKIP", "no_signal"),
    ]
    ev = build_symbol_evaluation("TSLA", _timeline_summary(), trades, [], None)

    assert ev["trade_types"]["REDUCE"] == 1
    assert ev["trade_types"]["SELL"] == 1
    assert ev["trade_types"]["SKIP"] == 3
    assert ev["skip_reasons"]["no_position_to_reduce"] == 2
    assert ev["skip_reasons"]["no_signal"] == 1


def test_symbol_evaluation_preserves_timeline_summary_fields() -> None:
    summary = _timeline_summary(
        first_action="REDUCE",
        last_action="NO_ACTION",
        score_change=-16,
        max_score=45,
        min_score=27,
    )
    ev = build_symbol_evaluation("TSLA", summary, [], [], None)

    assert ev["first_action"] == "REDUCE"
    assert ev["last_action"] == "NO_ACTION"
    assert ev["score_change"] == -16
    assert ev["max_score"] == 45
    assert ev["min_score"] == 27


def test_symbol_evaluation_realized_pnl_sum() -> None:
    closed = [
        {"symbol": "AAPL", "realized_pnl": 50.0},
        {"symbol": "AAPL", "realized_pnl": -20.0},
    ]
    ev = build_symbol_evaluation("AAPL", _timeline_summary(), [], closed, None)

    assert ev["realized_pnl"] == pytest.approx(30.0)


def test_symbol_evaluation_realized_pnl_none_when_no_closes() -> None:
    ev = build_symbol_evaluation("AAPL", _timeline_summary(), [], [], None)
    assert ev["realized_pnl"] is None


def test_symbol_evaluation_open_position_passed_through() -> None:
    op = {"symbol": "AAPL", "quantity": 10.0, "market_value": 1500.0}
    ev = build_symbol_evaluation("AAPL", _timeline_summary(), [], [], op)
    assert ev["open_position"] == op


def test_symbol_evaluation_closed_position_is_last_entry() -> None:
    closed = [
        {"symbol": "AAPL", "trade_type": "REDUCE", "realized_pnl": 20.0},
        {"symbol": "AAPL", "trade_type": "SELL", "realized_pnl": 30.0},
    ]
    ev = build_symbol_evaluation("AAPL", _timeline_summary(), [], closed, None)
    assert ev["closed_position"]["trade_type"] == "SELL"


# ── build_highlights ───────────────────────────────────────────────────────────


def test_highlights_empty_evaluations() -> None:
    h = build_highlights([], [], {})
    assert h["best_symbol"] is None
    assert h["worst_symbol"] is None
    assert h["most_active_symbol"] is None


def test_highlights_best_worst_by_realized_pnl() -> None:
    evals = [
        {"symbol": "AAPL", "realized_pnl": 100.0, "trade_count": 1, "skip_count": 0},
        {"symbol": "NVDA", "realized_pnl": -50.0, "trade_count": 1, "skip_count": 0},
        {"symbol": "TSLA", "realized_pnl": 25.0, "trade_count": 1, "skip_count": 0},
    ]
    h = build_highlights(evals, [], {})
    assert h["best_symbol"] == "AAPL"
    assert h["worst_symbol"] == "NVDA"


def test_highlights_best_worst_fallback_to_score_change() -> None:
    evals = [
        {
            "symbol": "AAPL",
            "realized_pnl": None,
            "score_change": 20,
            "trade_count": 0,
            "skip_count": 1,
        },
        {
            "symbol": "TSLA",
            "realized_pnl": None,
            "score_change": -10,
            "trade_count": 0,
            "skip_count": 1,
        },
    ]
    h = build_highlights(evals, [], {})
    assert h["best_symbol"] == "AAPL"
    assert h["worst_symbol"] == "TSLA"


def test_highlights_most_active_by_total_interactions() -> None:
    evals = [
        {
            "symbol": "AAPL",
            "realized_pnl": None,
            "score_change": 0,
            "trade_count": 1,
            "skip_count": 1,
        },
        {
            "symbol": "NVDA",
            "realized_pnl": None,
            "score_change": 0,
            "trade_count": 3,
            "skip_count": 5,
        },
        {
            "symbol": "TSLA",
            "realized_pnl": None,
            "score_change": 0,
            "trade_count": 0,
            "skip_count": 2,
        },
    ]
    h = build_highlights(evals, [], {})
    assert h["most_active_symbol"] == "NVDA"


def test_highlights_largest_score_drop_and_jump() -> None:
    timelines = [
        _timeline("AAPL", changes=[_change("2025-01-01", "2025-01-08", -13)]),
        _timeline("NVDA", changes=[_change("2025-01-01", "2025-01-08", 8)]),
        _timeline(
            "TSLA",
            changes=[
                _change("2025-01-01", "2025-01-08", -5),
                _change("2025-01-08", "2025-01-15", 4),
            ],
        ),
    ]
    evals = [
        {
            "symbol": "AAPL",
            "realized_pnl": None,
            "score_change": -13,
            "trade_count": 0,
            "skip_count": 0,
        },
        {
            "symbol": "NVDA",
            "realized_pnl": None,
            "score_change": 8,
            "trade_count": 0,
            "skip_count": 0,
        },
        {
            "symbol": "TSLA",
            "realized_pnl": None,
            "score_change": -1,
            "trade_count": 0,
            "skip_count": 0,
        },
    ]
    h = build_highlights(evals, timelines, {})

    assert h["largest_score_drop"]["symbol"] == "AAPL"
    assert h["largest_score_drop"]["delta"] == -13
    assert h["largest_score_jump"]["symbol"] == "NVDA"
    assert h["largest_score_jump"]["delta"] == 8


def test_highlights_most_common_skip_reason() -> None:
    skip_breakdown = {"no_position_to_reduce": 5, "insufficient_cash": 2}
    evals = [
        {
            "symbol": "AAPL",
            "realized_pnl": None,
            "score_change": 0,
            "trade_count": 0,
            "skip_count": 7,
        }
    ]
    h = build_highlights(evals, [], skip_breakdown)
    assert h["most_common_skip_reason"] == "no_position_to_reduce"


# ── build_evaluation (top-level) ───────────────────────────────────────────────


def test_build_evaluation_top_level_keys() -> None:
    result = build_evaluation(
        replay_batch_id="batch-123",
        date_range={"start_date": "2025-01-01", "end_date": "2025-03-26"},
        symbols=["AAPL", "NVDA"],
        run_counts={"total": 5, "completed": 5, "failed": 0, "queued": 0, "running": 0},
        timelines=[_timeline("AAPL"), _timeline("NVDA")],
        backtest_run_id="run-abc",
        backtest_run_fields=_run_fields(),
        backtest_summary_json=_summary_json(),
        backtest_trades=[],
    )

    assert result["replay_batch_id"] == "batch-123"
    assert result["backtest_run_id"] == "run-abc"
    assert result["date_range"]["start_date"] == "2025-01-01"
    assert result["symbols"] == ["AAPL", "NVDA"]
    assert "run_counts" in result
    assert "portfolio_result" in result
    assert "symbol_evaluations" in result
    assert "highlights" in result


def test_build_evaluation_symbol_evaluations_count() -> None:
    result = build_evaluation(
        replay_batch_id="b",
        date_range={"start_date": "2025-01-01", "end_date": "2025-01-08"},
        symbols=["AAPL", "TSLA", "NVDA"],
        run_counts={"total": 2, "completed": 2, "failed": 0, "queued": 0, "running": 0},
        timelines=[_timeline("AAPL"), _timeline("TSLA"), _timeline("NVDA")],
        backtest_run_id="r",
        backtest_run_fields=_run_fields(),
        backtest_summary_json=_summary_json(),
        backtest_trades=[],
    )

    assert len(result["symbol_evaluations"]) == 3
    syms = [e["symbol"] for e in result["symbol_evaluations"]]
    assert "AAPL" in syms and "TSLA" in syms and "NVDA" in syms


def test_build_evaluation_trades_routed_to_correct_symbol() -> None:
    trades = [
        _trade("AAPL", "BUY"),
        _trade("TSLA", "REDUCE"),
        _trade("TSLA", "SKIP", "no_signal"),
    ]
    result = build_evaluation(
        replay_batch_id="b",
        date_range={"start_date": "2025-01-01", "end_date": "2025-01-08"},
        symbols=["AAPL", "TSLA"],
        run_counts={"total": 1, "completed": 1, "failed": 0, "queued": 0, "running": 0},
        timelines=[_timeline("AAPL"), _timeline("TSLA")],
        backtest_run_id="r",
        backtest_run_fields=_run_fields(),
        backtest_summary_json=_summary_json(),
        backtest_trades=trades,
    )

    evals = {e["symbol"]: e for e in result["symbol_evaluations"]}
    assert evals["AAPL"]["trade_count"] == 1
    assert evals["AAPL"]["skip_count"] == 0
    assert evals["TSLA"]["trade_count"] == 1
    assert evals["TSLA"]["skip_count"] == 1


def test_build_evaluation_empty_timelines() -> None:
    result = build_evaluation(
        replay_batch_id="b",
        date_range={"start_date": "2025-01-01", "end_date": "2025-01-08"},
        symbols=[],
        run_counts={"total": 1, "completed": 1, "failed": 0, "queued": 0, "running": 0},
        timelines=[],
        backtest_run_id="r",
        backtest_run_fields=_run_fields(),
        backtest_summary_json=_summary_json(),
        backtest_trades=[],
    )

    assert result["symbol_evaluations"] == []
    assert result["highlights"]["best_symbol"] is None
