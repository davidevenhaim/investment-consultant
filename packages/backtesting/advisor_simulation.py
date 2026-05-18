"""Follow-the-Advisor Strategy Simulation (M11.1).

Design rules
------------
- Deterministic and DB-only (no external API calls).
- No LLM, no live trading, no order placement.
- User-scoped: only the owning user's recommendations are used.
- Graceful: missing price bars produce SKIP trades or INSUFFICIENT_DATA, never 500.
- Simple average-cost tracking enables basic W/L accounting on SELL/REDUCE.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Deterministic display-string helpers ──────────────────────────────────────


def _fmt_currency(amount: float) -> str:
    """Format a non-negative dollar amount: '$12,543.53'."""
    return f"${amount:,.2f}"


def _fmt_signed_currency(delta: float) -> str:
    """Format a signed dollar amount: '+$2,543.53' or '-$123.45'."""
    if delta >= 0:
        return f"+${delta:,.2f}"
    return f"-${abs(delta):,.2f}"


def _fmt_signed_pct(rate: float | None) -> str:
    """Format a rate as a signed percentage (0.25 → '+25.00%'). Returns 'N/A' if None."""
    if rate is None:
        return "N/A"
    sign = "+" if rate >= 0 else ""
    return f"{sign}{rate * 100:.2f}%"


def _fmt_relative_pp(rate: float | None) -> str:
    """Format a relative return rate in percentage points.

    Example: 0.1692 → '+16.92 percentage points'.
    Returns 'N/A' if None.
    """
    if rate is None:
        return "N/A"
    sign = "+" if rate >= 0 else ""
    return f"{sign}{rate * 100:.2f} percentage points"


def _fmt_drawdown(rate: float | None) -> str:
    """Format a drawdown rate (typically negative): '-3.19%'. Returns 'N/A' if None."""
    if rate is None:
        return "N/A"
    return f"{rate * 100:.2f}%"


# ── Action → target portfolio weight mapping ──────────────────────────────────

_TARGET_WEIGHTS: dict[str, float] = {
    "STRONG_BUY": 0.20,
    "BUY_CANDIDATE": 0.10,
    "BUY": 0.15,
    "HOLD": 0.0,          # no change
    "WATCHLIST": 0.0,     # no change
    "NO_ACTION": 0.0,     # no change
    "REDUCE": -0.50,      # sentinel: reduce by 50 %
    "SELL": -1.0,         # sentinel: close full position
}

_BUY_ACTIONS = {"STRONG_BUY", "BUY_CANDIDATE", "BUY"}
_SKIP_ACTIONS = {"HOLD", "WATCHLIST", "NO_ACTION"}

# Minimum cash-purchase threshold (avoid tiny fractional buys)
_MIN_PURCHASE_CASH = 10.0
# Days to look forward for execution price
_PRICE_TOLERANCE_DAYS = 5


# ── Internal state dataclasses (no DB) ────────────────────────────────────────


@dataclass
class _Position:
    symbol: str
    qty: float = 0.0
    avg_cost: float = 0.0   # volume-weighted average cost

    def update_buy(self, qty: float, price: float) -> None:
        total_cost = self.avg_cost * self.qty + price * qty
        self.qty += qty
        self.avg_cost = total_cost / self.qty if self.qty > 0 else 0.0

    def close_partial(self, qty: float) -> float:
        """Remove qty shares; return realised P/L."""
        qty = min(qty, self.qty)
        realised_pnl = qty * (0.0 - self.avg_cost)  # will be updated by caller
        self.qty = max(0.0, self.qty - qty)
        if self.qty == 0:
            self.avg_cost = 0.0
        return realised_pnl


@dataclass
class _SimState:
    cash: float
    positions: dict[str, _Position] = field(default_factory=dict)
    peak_equity: float = 0.0
    max_drawdown: float = 0.0

    def equity(self, prices: dict[str, float]) -> float:
        pos_val = sum(
            p.qty * prices.get(p.symbol, 0.0) for p in self.positions.values()
        )
        return self.cash + pos_val

    def position_weight(self, symbol: str, prices: dict[str, float]) -> float:
        eq = self.equity(prices)
        if eq <= 0:
            return 0.0
        pos = self.positions.get(symbol)
        if pos is None:
            return 0.0
        return (pos.qty * prices.get(symbol, 0.0)) / eq

    def update_drawdown(self, current_equity: float) -> float:
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
        dd = (current_equity - self.peak_equity) / self.peak_equity if self.peak_equity > 0 else 0.0
        if dd < self.max_drawdown:
            self.max_drawdown = dd
        return dd


# ── Price lookup helpers ───────────────────────────────────────────────────────


def _find_price(
    date: dt.date,
    bars_by_symbol: dict[str, dict[dt.date, float]],
    symbol: str,
    forward_only: bool = True,
    tolerance: int = _PRICE_TOLERANCE_DAYS,
) -> tuple[float | None, dt.date | None]:
    """Return (close_price, actual_date) within tolerance days.

    If ``forward_only`` is True, only looks at date and later.
    Otherwise looks backwards (useful for equity valuation).
    """
    sym_bars = bars_by_symbol.get(symbol.upper(), {})
    if not sym_bars:
        return None, None

    if forward_only:
        for offset in range(tolerance + 1):
            d = date + dt.timedelta(days=offset)
            if d in sym_bars:
                return sym_bars[d], d
    else:
        # Look backwards up to tolerance
        for offset in range(tolerance + 1):
            d = date - dt.timedelta(days=offset)
            if d in sym_bars:
                return sym_bars[d], d

    return None, None


def _latest_price_on_or_before(
    date: dt.date,
    bars_by_symbol: dict[str, dict[dt.date, float]],
    symbol: str,
) -> float | None:
    """Return most recent close price on or before date; None if unavailable."""
    sym_bars = bars_by_symbol.get(symbol.upper(), {})
    candidates = [d for d in sym_bars if d <= date]
    if not candidates:
        return None
    return sym_bars[max(candidates)]


# ── Trade-record builder ───────────────────────────────────────────────────────


def _make_trade_row(
    backtest_run_id: Any,
    user_id: Any,
    symbol: str,
    recommendation_id: Any,
    research_run_id: Any,
    action: str,
    trade_type: str,
    trade_date: dt.datetime,
    price: float | None = None,
    quantity: float | None = None,
    cash_delta: float | None = None,
    position_before: float | None = None,
    position_after: float | None = None,
    reason: str | None = None,
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from db.models import AdvisorBacktestTrade
    return {
        "model_class": AdvisorBacktestTrade,
        "backtest_run_id": backtest_run_id,
        "user_id": user_id,
        "symbol": symbol,
        "recommendation_id": recommendation_id,
        "research_run_id": research_run_id,
        "action": action,
        "trade_type": trade_type,
        "trade_date": trade_date,
        "price": price,
        "quantity": quantity,
        "cash_delta": cash_delta,
        "position_before": position_before,
        "position_after": position_after,
        "reason": reason,
        "raw_json": raw or {},
    }


def _replay_apply_executed_trade(state: _SimState, t: dict[str, Any]) -> None:
    """Apply a BUY / SELL / REDUCE row when replaying the portfolio for the equity curve.

    Must mirror the executed trade rows from the recommendation pass: same cash_delta,
    quantities, and position_after for REDUCE so MTM equity matches that pass.
    """
    sym = t["symbol"].upper()
    tt = t["trade_type"]
    if tt == "BUY":
        state.cash += float(t["cash_delta"] or 0.0)
        if sym not in state.positions:
            state.positions[sym] = _Position(sym)
        state.positions[sym].update_buy(
            float(t["quantity"] or 0.0),
            float(t["price"] or 0.0),
        )
    elif tt == "SELL":
        state.cash += float(t["cash_delta"] or 0.0)
        state.positions[sym] = _Position(sym)
    elif tt == "REDUCE":
        state.cash += float(t["cash_delta"] or 0.0)
        if sym not in state.positions:
            state.positions[sym] = _Position(sym)
        pa = t["position_after"]
        state.positions[sym].qty = float(pa) if pa is not None else 0.0
        if state.positions[sym].qty <= 0.0:
            state.positions[sym].qty = 0.0
            state.positions[sym].avg_cost = 0.0
    else:  # pragma: no cover - defensive
        msg = f"replay: unexpected trade_type={tt!r}"
        raise ValueError(msg)


# ── Enriched summary builder ──────────────────────────────────────────────────


def _build_enriched_summary(
    *,
    initial_cash: float,
    final_equity: float,
    total_return: float,
    max_drawdown: float,
    bench_return: float | None,
    relative_return: float | None,
    bench_symbol: str,
    last_cash: float,
    last_pos_val: float,
    winning: int,
    losing: int,
    skipped: int,
    actual_trades: int,
    trade_dicts: list[dict[str, Any]],
    curve_state: _SimState,
    bars_by_symbol: dict[str, dict[dt.date, float]],
    end_date: dt.date,
    start_date: dt.date,
    recommendation_source: str = "ALL",
    scenario_name: str | None = None,
    recommendations_considered: int = 0,
) -> dict[str, Any]:
    """Build the full deterministic summary dict persisted in summary_json."""
    pnl_amount = final_equity - initial_cash
    traded_symbols = list({t["symbol"] for t in trade_dicts if t["trade_type"] != "SKIP"})

    from_str = start_date.strftime("%Y-%m-%d")
    to_str = end_date.strftime("%Y-%m-%d")
    human_summary = (
        f"Following the advisor from {from_str} to {to_str} would have turned "
        f"${initial_cash:,.2f} into ${final_equity:,.2f} "
        f"({'+' if total_return >= 0 else ''}{total_return:.1%} return)."
    )

    # ── trade_breakdown & skip_breakdown ───────────────────────────────────────
    trade_breakdown: dict[str, int] = {}
    skip_breakdown: dict[str, int] = {}
    for t in trade_dicts:
        tt = t["trade_type"]
        trade_breakdown[tt] = trade_breakdown.get(tt, 0) + 1
        if tt == "SKIP":
            reason = str(t.get("reason") or "unknown")
            skip_breakdown[reason] = skip_breakdown.get(reason, 0) + 1

    # ── open_positions (from final curve_state) ────────────────────────────────
    open_positions: list[dict[str, Any]] = []
    for sym, pos in curve_state.positions.items():
        if pos.qty <= 0.0:
            continue
        last_p = _latest_price_on_or_before(end_date, bars_by_symbol, sym)
        mv = pos.qty * last_p if last_p is not None else 0.0
        cost_basis_total = pos.qty * pos.avg_cost
        unreal_pnl = mv - cost_basis_total if last_p is not None else 0.0
        unreal_ret = unreal_pnl / cost_basis_total if cost_basis_total > 0 else 0.0
        weight = mv / final_equity if final_equity > 0 else 0.0
        open_positions.append({
            "symbol": sym,
            "quantity": round(pos.qty, 6),
            "avg_cost": round(pos.avg_cost, 4),
            "last_price": round(last_p, 4) if last_p is not None else None,
            "market_value": round(mv, 4),
            "unrealized_pnl": round(unreal_pnl, 4),
            "unrealized_return_pct": round(unreal_ret, 6),
            "weight": round(weight, 6),
        })
    open_positions.sort(key=lambda x: x["market_value"], reverse=True)

    # ── closed_positions (from SELL / REDUCE trade rows) ──────────────────────
    closed_positions: list[dict[str, Any]] = []
    for t in trade_dicts:
        if t["trade_type"] not in ("SELL", "REDUCE"):
            continue
        raw = t.get("raw_json") or {}
        pnl: float | None = raw.get("pnl")
        avg_cost: float | None = raw.get("avg_cost")
        qty = float(t["quantity"] or 0.0)
        exit_price = float(t["price"] or 0.0)
        cost_basis = qty * avg_cost if avg_cost is not None else None
        ret: float | None = (
            pnl / cost_basis
            if (pnl is not None and cost_basis is not None and cost_basis > 0)
            else None
        )
        closed_positions.append({
            "symbol": t["symbol"],
            "trade_type": t["trade_type"],
            "quantity": round(qty, 6),
            "entry_avg_cost": round(avg_cost, 4) if avg_cost is not None else None,
            "exit_price": round(exit_price, 4),
            "realized_pnl": round(pnl, 4) if pnl is not None else None,
            "realized_return_pct": round(ret, 6) if ret is not None else None,
        })

    # ── best / worst realized trades ──────────────────────────────────────────
    scored = [c for c in closed_positions if c["realized_pnl"] is not None]
    best_realized_trade: dict[str, Any] | None = None
    worst_realized_trade: dict[str, Any] | None = None
    if scored:
        best_realized_trade = max(scored, key=lambda x: x["realized_pnl"])
        worst_realized_trade = min(scored, key=lambda x: x["realized_pnl"])

    # ── top open position (by market_value) ────────────────────────────────────
    top_open_position: dict[str, Any] | None = open_positions[0] if open_positions else None

    # ── benchmark_summary ─────────────────────────────────────────────────────
    benchmark_summary: dict[str, Any] = {
        "benchmark_symbol": bench_symbol,
        "benchmark_return_pct": round(bench_return, 8) if bench_return is not None else None,
        "relative_return_pct": round(relative_return, 8) if relative_return is not None else None,
        "outperformed_benchmark": (
            bool(relative_return > 0) if relative_return is not None else None
        ),
    }

    return {
        # ── legacy fields (backwards compat) ──────────────────────────────────
        "initial_cash": round(initial_cash, 4),
        "final_equity": round(final_equity, 4),
        "profit_loss_amount": round(pnl_amount, 4),
        "total_return_pct": round(total_return, 8),
        "benchmark_return_pct": round(bench_return, 8) if bench_return is not None else None,
        "relative_return_pct": round(relative_return, 8) if relative_return is not None else None,
        "max_drawdown_pct": round(max_drawdown, 8),
        "total_trades": actual_trades,
        "winning_trades": winning,
        "losing_trades": losing,
        "skipped_recommendations": skipped,
        "traded_symbols": traded_symbols,
        "human_summary": human_summary,
        # ── display strings ────────────────────────────────────────────────────
        "profit_loss_display": _fmt_signed_currency(pnl_amount),
        "total_return_display": _fmt_signed_pct(total_return),
        "benchmark_return_display": _fmt_signed_pct(bench_return),
        "relative_return_display": _fmt_relative_pp(relative_return),
        "max_drawdown_display": _fmt_drawdown(max_drawdown),
        # ── final portfolio state ──────────────────────────────────────────────
        "final_cash": round(last_cash, 4),
        "final_cash_display": _fmt_currency(max(last_cash, 0.0)),
        "final_positions_value": round(last_pos_val, 4),
        "final_positions_value_display": _fmt_currency(last_pos_val),
        # ── position details ──────────────────────────────────────────────────
        "open_positions": open_positions,
        "closed_positions": closed_positions,
        "best_realized_trade": best_realized_trade,
        "worst_realized_trade": worst_realized_trade,
        "top_open_position": top_open_position,
        # ── trade analysis ────────────────────────────────────────────────────
        "trade_breakdown": trade_breakdown,
        "skip_breakdown": skip_breakdown,
        # ── benchmark ─────────────────────────────────────────────────────────
        "benchmark_summary": benchmark_summary,
        # ── recommendation source ─────────────────────────────────────────────
        "recommendation_source": recommendation_source,
        "scenario_name": scenario_name,
        "recommendations_considered": recommendations_considered,
    }


# ── Main simulation engine ─────────────────────────────────────────────────────


async def run_advisor_backtest(
    session: AsyncSession,
    user_id: uuid.UUID,
    start_date: dt.date,
    end_date: dt.date,
    initial_cash: float,
    benchmark_symbol: str = "SPY",
    name: str | None = None,
    assumptions: dict[str, Any] | None = None,
    recommendation_source: str = "ALL",
    scenario_name: str | None = None,
    pinned_run_ids: list[uuid.UUID] | None = None,
    initial_positions: list[dict[str, Any]] | None = None,
) -> Any:
    """Run a follow-the-advisor simulation and persist results.

    When *pinned_run_ids* is provided the date-range / source filter is
    bypassed and those runs are used directly (e.g. a replay batch backtest).

    Returns the persisted AdvisorBacktestRun ORM row with relationships loaded.
    """
    from datetime import UTC

    from db.enums import ResearchRunStatus
    from db.models import (
        AdvisorBacktestEquityPoint,
        AdvisorBacktestRun,
        AdvisorBacktestTrade,
        NeutralRecommendation,
        ResearchRun,
    )
    from market_data.repository import MarketPriceRepository
    from sqlalchemy import select

    mpr = MarketPriceRepository(session)
    assumptions_used = assumptions or {}
    assumptions_used["target_weights"] = _TARGET_WEIGHTS
    assumptions_used["price_tolerance_days"] = _PRICE_TOLERANCE_DAYS
    assumptions_used["recommendation_source"] = recommendation_source
    assumptions_used["scenario_name"] = scenario_name

    # 1. Determine which completed runs to draw recommendations from.
    if pinned_run_ids is not None:
        # Caller pre-filtered (e.g. replay batch) — skip date/source filter.
        effective_run_ids: list[uuid.UUID] = pinned_run_ids
    else:
        from sqlalchemy import not_

        _src = recommendation_source.upper()
        source_filters = []
        if _src == "SCENARIO":
            source_filters.append(ResearchRun.metadata_json.contains({"scenario_seed": True}))
            if scenario_name:
                source_filters.append(
                    ResearchRun.metadata_json.contains({"scenario": scenario_name})
                )
        elif _src == "REAL":
            source_filters.append(
                not_(ResearchRun.metadata_json.contains({"scenario_seed": True}))
            )
        # ALL: no extra filters

        runs_result = await session.execute(
            select(ResearchRun).where(
                ResearchRun.user_id == user_id,
                ResearchRun.status == ResearchRunStatus.COMPLETED.value,
                ResearchRun.finished_at >= dt.datetime.combine(start_date, dt.time.min, tzinfo=UTC),
                ResearchRun.finished_at <= dt.datetime.combine(end_date, dt.time.max, tzinfo=UTC),
                *source_filters,
            )
        )
        effective_run_ids = [r.id for r in runs_result.scalars().all()]

    # 2. Fetch neutral recommendations for those runs, sorted by created_at asc
    recs: list[NeutralRecommendation] = []
    if effective_run_ids:
        recs_result = await session.execute(
            select(NeutralRecommendation)
            .where(NeutralRecommendation.research_run_id.in_(effective_run_ids))
            .order_by(NeutralRecommendation.created_at.asc(), NeutralRecommendation.symbol.asc())
        )
        recs = list(recs_result.scalars().all())

    # 3. Determine all symbols we'll need prices for
    ip_symbols = {ip["symbol"].upper() for ip in (initial_positions or [])}
    all_symbols = {r.symbol.upper() for r in recs} | {benchmark_symbol.upper()} | ip_symbols

    # 4. Fetch price bars for all symbols in the period (with buffer)
    buf_start = start_date - dt.timedelta(days=10)
    buf_end = end_date + dt.timedelta(days=14)

    bars_by_symbol: dict[str, dict[dt.date, float]] = {}
    for sym in all_symbols:
        bars = await mpr.get_bars(sym, start_date=buf_start, end_date=buf_end)
        bars_by_symbol[sym] = {b.price_date: float(b.adjusted_close or b.close) for b in bars}

    # 4.5. Validate and price initial positions
    # seeded: list of (symbol, quantity, entry_price) resolved at start_date
    seeded: list[tuple[str, float, float]] = []
    if initial_positions:
        total_ip_cost = 0.0
        for ip in initial_positions:
            sym = ip["symbol"].upper()
            qty = float(ip["quantity"])
            entry_price, _ = _find_price(start_date, bars_by_symbol, sym, forward_only=True)
            if entry_price is None:
                msg = (
                    f"Cannot price initial position {sym}: "
                    f"no price bars found near {start_date}."
                )
                raise ValueError(msg)
            total_ip_cost += qty * entry_price
            seeded.append((sym, qty, entry_price))
        if total_ip_cost > initial_cash:
            msg = (
                f"Initial positions total cost {total_ip_cost:.2f} "
                f"exceeds initial_cash {initial_cash:.2f}."
            )
            raise ValueError(msg)
        assumptions_used["initial_positions"] = [
            {"symbol": sym, "quantity": qty, "entry_price": round(entry_p, 4)}
            for sym, qty, entry_p in seeded
        ]

    # 5. Build sorted list of trading calendar dates in range
    all_bar_dates = (
        d
        for bar_dates in bars_by_symbol.values()
        for d in bar_dates
        if start_date <= d <= end_date
    )
    trading_dates = sorted(set(all_bar_dates))

    # Snapshot rec count after source filtering (before skipping by date / action)
    recommendations_considered = len(recs)

    # 6. Initialise simulation state
    state = _SimState(cash=initial_cash)
    state.peak_equity = initial_cash

    # Seed initial positions into simulation state (before processing recommendations)
    for sym, qty, entry_p in seeded:
        state.cash -= qty * entry_p
        if sym not in state.positions:
            state.positions[sym] = _Position(sym)
        state.positions[sym].update_buy(qty, entry_p)

    trade_dicts: list[dict[str, Any]] = []
    winning = 0
    losing = 0
    skipped = 0

    # 7. Process each recommendation in chronological order
    for rec in recs:
        rec_date = rec.created_at.date() if rec.created_at else end_date
        if rec_date < start_date or rec_date > end_date:
            continue

        action = rec.action.upper()
        symbol = rec.symbol.upper()
        target_w = _TARGET_WEIGHTS.get(action, 0.0)

        # Look up execution price
        exec_price, exec_date = _find_price(rec_date, bars_by_symbol, symbol, forward_only=True)

        trade_date_dt = dt.datetime.combine(
            exec_date or rec_date, dt.time(16, 0), tzinfo=UTC
        )

        # SKIP actions — record skip, continue
        if action in _SKIP_ACTIONS:
            skipped += 1
            trade_dicts.append(_make_trade_row(
                backtest_run_id=None,
                user_id=user_id,
                symbol=symbol,
                recommendation_id=rec.id,
                research_run_id=rec.research_run_id,
                action=action,
                trade_type="SKIP",
                trade_date=trade_date_dt,
                reason="hold_or_no_action",
                raw={"rec_action": action},
            ))
            continue

        # Missing execution price
        if exec_price is None:
            skipped += 1
            trade_dicts.append(_make_trade_row(
                backtest_run_id=None,
                user_id=user_id,
                symbol=symbol,
                recommendation_id=rec.id,
                research_run_id=rec.research_run_id,
                action=action,
                trade_type="SKIP",
                trade_date=trade_date_dt,
                reason="missing_execution_price",
                raw={"rec_date": str(rec_date)},
            ))
            continue

        # Get current prices for weight calculation
        current_prices: dict[str, float] = {}
        for sym in state.positions:
            p, _ = _find_price(rec_date, bars_by_symbol, sym, forward_only=False, tolerance=10)
            if p:
                current_prices[sym] = p
        current_prices[symbol] = exec_price

        pos = state.positions.get(symbol, _Position(symbol))
        pos_qty_before = pos.qty

        if action == "SELL":
            if pos_qty_before <= 0:
                trade_dicts.append(_make_trade_row(
                    backtest_run_id=None, user_id=user_id, symbol=symbol,
                    recommendation_id=rec.id, research_run_id=rec.research_run_id,
                    action=action, trade_type="SKIP", trade_date=trade_date_dt,
                    reason="no_position_to_sell",
                ))
                skipped += 1
                continue
            avg_cost_at_exit = pos.avg_cost
            proceeds = pos_qty_before * exec_price
            pnl = proceeds - pos_qty_before * avg_cost_at_exit
            if pnl > 0:
                winning += 1
            elif pnl < 0:
                losing += 1
            state.cash += proceeds
            pos.qty = 0.0
            pos.avg_cost = 0.0
            state.positions[symbol] = pos
            trade_dicts.append(_make_trade_row(
                backtest_run_id=None, user_id=user_id, symbol=symbol,
                recommendation_id=rec.id, research_run_id=rec.research_run_id,
                action=action, trade_type="SELL", trade_date=trade_date_dt,
                price=exec_price, quantity=pos_qty_before,
                cash_delta=proceeds, position_before=pos_qty_before, position_after=0.0,
                raw={"pnl": round(pnl, 4), "avg_cost": round(avg_cost_at_exit, 4)},
            ))

        elif action == "REDUCE":
            if pos_qty_before <= 0:
                trade_dicts.append(_make_trade_row(
                    backtest_run_id=None, user_id=user_id, symbol=symbol,
                    recommendation_id=rec.id, research_run_id=rec.research_run_id,
                    action=action, trade_type="SKIP", trade_date=trade_date_dt,
                    reason="no_position_to_reduce",
                ))
                skipped += 1
                continue
            sell_qty = pos_qty_before * 0.5
            proceeds = sell_qty * exec_price
            pnl = proceeds - sell_qty * pos.avg_cost
            if pnl > 0:
                winning += 1
            elif pnl < 0:
                losing += 1
            state.cash += proceeds
            pos.qty -= sell_qty
            if pos.qty <= 0:
                pos.qty = 0.0
                pos.avg_cost = 0.0
            state.positions[symbol] = pos
            trade_dicts.append(_make_trade_row(
                backtest_run_id=None, user_id=user_id, symbol=symbol,
                recommendation_id=rec.id, research_run_id=rec.research_run_id,
                action=action, trade_type="REDUCE", trade_date=trade_date_dt,
                price=exec_price, quantity=sell_qty,
                cash_delta=proceeds, position_before=pos_qty_before,
                position_after=pos.qty,
                raw={"pnl": round(pnl, 4), "avg_cost": round(pos.avg_cost, 4)},
            ))

        elif action in _BUY_ACTIONS:
            current_w = state.position_weight(symbol, current_prices)
            if current_w >= target_w - 0.001:
                trade_dicts.append(_make_trade_row(
                    backtest_run_id=None, user_id=user_id, symbol=symbol,
                    recommendation_id=rec.id, research_run_id=rec.research_run_id,
                    action=action, trade_type="SKIP", trade_date=trade_date_dt,
                    reason="already_at_or_above_target",
                    raw={"current_weight": round(current_w, 4), "target_weight": target_w},
                ))
                skipped += 1
                continue

            target_equity = state.equity(current_prices)
            target_position_value = target_w * target_equity
            current_position_value = current_w * target_equity
            buy_value = target_position_value - current_position_value
            buy_value = min(buy_value, state.cash)

            if buy_value < _MIN_PURCHASE_CASH:
                trade_dicts.append(_make_trade_row(
                    backtest_run_id=None, user_id=user_id, symbol=symbol,
                    recommendation_id=rec.id, research_run_id=rec.research_run_id,
                    action=action, trade_type="SKIP", trade_date=trade_date_dt,
                    reason="insufficient_cash",
                    raw={"buy_value": round(buy_value, 4), "cash": round(state.cash, 4)},
                ))
                skipped += 1
                continue

            qty = buy_value / exec_price
            cost = qty * exec_price
            state.cash -= cost
            if symbol not in state.positions:
                state.positions[symbol] = _Position(symbol)
            state.positions[symbol].update_buy(qty, exec_price)
            trade_dicts.append(_make_trade_row(
                backtest_run_id=None, user_id=user_id, symbol=symbol,
                recommendation_id=rec.id, research_run_id=rec.research_run_id,
                action=action, trade_type="BUY", trade_date=trade_date_dt,
                price=exec_price, quantity=qty,
                cash_delta=-cost, position_before=pos_qty_before,
                position_after=state.positions[symbol].qty,
                raw={"target_weight": target_w, "buy_value": round(buy_value, 4)},
            ))
        # ignore unknown actions silently

    # 8. Build equity curve: replay executed trades chronologically per date (no lookahead)
    benchmark_bars = bars_by_symbol.get(benchmark_symbol.upper(), {})
    bench_start_price: float | None = None
    bench_dates = sorted(benchmark_bars)
    if bench_dates:
        first_bench = next((d for d in bench_dates if d >= start_date), None)
        if first_bench:
            bench_start_price = benchmark_bars[first_bench]

    executed_seq: list[tuple[int, dict[str, Any]]] = [
        (i, t)
        for i, t in enumerate(trade_dicts)
        if t["trade_type"] in ("BUY", "SELL", "REDUCE")
    ]
    executed_seq.sort(key=lambda it: (it[1]["trade_date"], it[0]))

    curve_state = _SimState(cash=initial_cash)
    curve_state.peak_equity = initial_cash

    # Mirror initial positions into the equity-curve replay state
    for sym, qty, entry_p in seeded:
        curve_state.cash -= qty * entry_p
        if sym not in curve_state.positions:
            curve_state.positions[sym] = _Position(sym)
        curve_state.positions[sym].update_buy(qty, entry_p)

    ex_i = 0

    equity_point_rows: list[dict[str, Any]] = []
    last_equity = float(initial_cash)
    last_cash = float(initial_cash)
    last_pos_val = 0.0
    for d in trading_dates:
        while ex_i < len(executed_seq) and executed_seq[ex_i][1]["trade_date"].date() <= d:
            _replay_apply_executed_trade(curve_state, executed_seq[ex_i][1])
            ex_i += 1

        day_prices: dict[str, float] = {}
        for sym in curve_state.positions:
            p = _latest_price_on_or_before(d, bars_by_symbol, sym)
            if p:
                day_prices[sym] = p
        eq = curve_state.equity(day_prices)
        last_equity = eq
        last_cash = float(curve_state.cash)
        pos_val = eq - curve_state.cash
        last_pos_val = max(pos_val, 0.0)
        dd = curve_state.update_drawdown(eq)

        bench_val: float | None = None
        if bench_start_price and d in benchmark_bars and initial_cash > 0:
            bench_val = initial_cash * (benchmark_bars[d] / bench_start_price)

        equity_point_rows.append({
            "date": d,
            "equity": round(eq, 4),
            "cash": round(curve_state.cash, 4),
            "positions_value": round(max(pos_val, 0.0), 4),
            "drawdown_pct": round(dd, 8),
            "benchmark_value": round(bench_val, 4) if bench_val else None,
        })

    # 9. Final equity = last curve point (fills after end_date excluded from curve)
    final_equity = last_equity
    total_return = (final_equity - initial_cash) / initial_cash if initial_cash > 0 else 0.0
    max_drawdown = curve_state.max_drawdown
    cash_final_value = last_cash

    # Benchmark return
    bench_return: float | None = None
    if bench_start_price:
        bench_end_price = _latest_price_on_or_before(
            end_date, bars_by_symbol, benchmark_symbol.upper()
        )
        if bench_end_price and bench_start_price > 0:
            bench_return = (bench_end_price - bench_start_price) / bench_start_price

    relative_return = (total_return - bench_return) if bench_return is not None else None

    # Determine run status
    actual_trades = sum(1 for t in trade_dicts if t["trade_type"] != "SKIP")
    status = "COMPLETED"
    if not trading_dates and recs:
        status = "INSUFFICIENT_DATA"

    # 10. Build enriched summary
    summary: dict[str, Any] = _build_enriched_summary(
        initial_cash=initial_cash,
        final_equity=final_equity,
        total_return=total_return,
        max_drawdown=max_drawdown,
        bench_return=bench_return,
        relative_return=relative_return,
        bench_symbol=benchmark_symbol,
        last_cash=last_cash,
        last_pos_val=last_pos_val,
        winning=winning,
        losing=losing,
        skipped=skipped,
        actual_trades=actual_trades,
        trade_dicts=trade_dicts,
        curve_state=curve_state,
        bars_by_symbol=bars_by_symbol,
        end_date=end_date,
        start_date=start_date,
        recommendation_source=recommendation_source,
        scenario_name=scenario_name,
        recommendations_considered=recommendations_considered,
    )

    # 11. Persist run
    run = AdvisorBacktestRun(
        user_id=user_id,
        name=name,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
        final_equity=final_equity,
        cash_final=cash_final_value,
        total_return_pct=total_return,
        benchmark_symbol=benchmark_symbol,
        benchmark_return_pct=bench_return,
        relative_return_pct=relative_return,
        max_drawdown_pct=max_drawdown,
        total_trades=actual_trades,
        winning_trades=winning,
        losing_trades=losing,
        status=status,
        assumptions_json=assumptions_used,
        summary_json=summary,
    )
    session.add(run)
    await session.flush()

    # 12. Persist trades
    for td in trade_dicts:
        td_copy = {k: v for k, v in td.items() if k != "model_class"}
        td_copy["backtest_run_id"] = run.id
        trade = AdvisorBacktestTrade(**td_copy)
        session.add(trade)

    # 13. Persist equity points
    for ep in equity_point_rows:
        session.add(AdvisorBacktestEquityPoint(backtest_run_id=run.id, **ep))

    await session.flush()

    # Reload with relationships eagerly so callers can access trades/equity_points
    from sqlalchemy.orm import selectinload

    run_result = await session.execute(
        select(AdvisorBacktestRun)
        .options(
            selectinload(AdvisorBacktestRun.trades),
            selectinload(AdvisorBacktestRun.equity_points),
        )
        .where(AdvisorBacktestRun.id == run.id)
    )
    run = run_result.scalar_one()

    logger.info(
        "advisor_backtest_completed",
        extra={
            "user_id": str(user_id),
            "start_date": str(start_date),
            "end_date": str(end_date),
            "total_trades": actual_trades,
            "final_equity": round(final_equity, 2),
            "total_return_pct": round(total_return, 4),
        },
    )
    return run
