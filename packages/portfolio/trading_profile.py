"""Deterministic behavioral trading profile engine.

All metrics are computed from raw execution records — no LLM involved.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from broker.ibkr.schemas import IBKRExecution

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass
class TradePair:
    symbol: str
    buy_price: float
    sell_price: float
    quantity: float
    buy_date: dt.datetime
    sell_date: dt.datetime

    @property
    def pnl_pct(self) -> float:
        return (self.sell_price - self.buy_price) / self.buy_price

    @property
    def holding_days(self) -> float:
        return (self.sell_date - self.buy_date).total_seconds() / 86_400

    @property
    def is_winner(self) -> bool:
        return self.pnl_pct > 0


@dataclass
class SymbolStats:
    symbol: str
    trade_pairs: list[TradePair] = field(default_factory=list)
    open_qty: float = 0.0

    @property
    def win_rate(self) -> float | None:
        if not self.trade_pairs:
            return None
        wins = sum(1 for p in self.trade_pairs if p.is_winner)
        return wins / len(self.trade_pairs)

    @property
    def avg_winner_pct(self) -> float | None:
        winners = [p.pnl_pct for p in self.trade_pairs if p.is_winner]
        return sum(winners) / len(winners) if winners else None

    @property
    def avg_loser_pct(self) -> float | None:
        losers = [p.pnl_pct for p in self.trade_pairs if not p.is_winner]
        return sum(losers) / len(losers) if losers else None


@dataclass
class TradingProfile:
    period_months: int
    as_of_date: dt.date

    total_executions: int = 0
    total_symbols_traded: int = 0

    win_rate: float | None = None
    avg_winner_pct: float | None = None
    avg_loser_pct: float | None = None
    profit_factor: float | None = None
    avg_holding_days: float | None = None

    disposition_effect_score: float | None = None
    concentration_score: float | None = None
    recency_bias_score: float | None = None

    behavioral_flags: list[str] = field(default_factory=list)
    per_symbol_stats: dict[str, object] = field(default_factory=dict)
    raw_metrics: dict[str, object] = field(default_factory=dict)


# ── FIFO matching ─────────────────────────────────────────────────────────────


def _fifo_match(executions: Sequence[IBKRExecution]) -> tuple[list[TradePair], dict[str, float]]:
    """Match BUY→SELL pairs via FIFO. Returns (completed_pairs, open_qty_by_symbol)."""
    buys_by_symbol: dict[str, list[IBKRExecution]] = defaultdict(list)
    pairs: list[TradePair] = []
    open_qty: dict[str, float] = defaultdict(float)

    sorted_execs = sorted(executions, key=lambda e: e.executed_at)

    for ex in sorted_execs:
        if ex.side == "BUY":
            buys_by_symbol[ex.symbol].append(ex)
            open_qty[ex.symbol] += ex.quantity
        else:  # SELL
            remaining = ex.quantity
            while remaining > 0 and buys_by_symbol[ex.symbol]:
                buy = buys_by_symbol[ex.symbol][0]
                matched = min(remaining, buy.quantity)
                pairs.append(
                    TradePair(
                        symbol=ex.symbol,
                        buy_price=float(buy.price),
                        sell_price=float(ex.price),
                        quantity=matched,
                        buy_date=buy.executed_at,
                        sell_date=ex.executed_at,
                    )
                )
                remaining -= matched
                if matched >= buy.quantity:
                    buys_by_symbol[ex.symbol].pop(0)
                    open_qty[ex.symbol] -= buy.quantity
                else:
                    # partial fill — replace first buy with remaining qty
                    remaining_qty = buy.quantity - matched
                    partial = IBKRExecution(**{**buy.model_dump(), "quantity": remaining_qty})
                    buys_by_symbol[ex.symbol][0] = partial
                    open_qty[ex.symbol] -= matched

    return pairs, dict(open_qty)


# ── individual metrics ────────────────────────────────────────────────────────


def _win_rate(pairs: list[TradePair]) -> float | None:
    if not pairs:
        return None
    return sum(1 for p in pairs if p.is_winner) / len(pairs)


def _avg_winner_pct(pairs: list[TradePair]) -> float | None:
    winners = [p.pnl_pct for p in pairs if p.is_winner]
    return sum(winners) / len(winners) if winners else None


def _avg_loser_pct(pairs: list[TradePair]) -> float | None:
    losers = [p.pnl_pct for p in pairs if not p.is_winner]
    return sum(losers) / len(losers) if losers else None


def _profit_factor(pairs: list[TradePair]) -> float | None:
    gross_wins = sum(p.pnl_pct * p.quantity * p.buy_price for p in pairs if p.is_winner)
    gross_losses = abs(sum(p.pnl_pct * p.quantity * p.buy_price for p in pairs if not p.is_winner))
    if gross_losses == 0:
        return None
    return gross_wins / gross_losses


def _avg_holding_days(pairs: list[TradePair]) -> float | None:
    if not pairs:
        return None
    return sum(p.holding_days for p in pairs) / len(pairs)


def _disposition_effect_score(pairs: list[TradePair]) -> float | None:
    """Positive → holding losers longer than winners (classic disposition effect).

    Score = (avg_loser_days - avg_winner_days) / avg_loser_days, clamped [0, 1].
    """
    winner_days = [p.holding_days for p in pairs if p.is_winner]
    loser_days = [p.holding_days for p in pairs if not p.is_winner]
    if not winner_days or not loser_days:
        return None
    avg_w = sum(winner_days) / len(winner_days)
    avg_l = sum(loser_days) / len(loser_days)
    if avg_l == 0:
        return 0.0
    raw = (avg_l - avg_w) / avg_l
    return max(0.0, min(1.0, raw))


def _concentration_score(executions: Sequence[IBKRExecution]) -> float | None:
    """Herfindahl index on volume by symbol — 0 = diversified, 1 = fully concentrated."""
    vol_by_symbol: dict[str, float] = defaultdict(float)
    for ex in executions:
        vol_by_symbol[ex.symbol] += ex.quantity * float(ex.price)
    total = sum(vol_by_symbol.values())
    if total == 0:
        return None
    shares = [v / total for v in vol_by_symbol.values()]
    return sum(s**2 for s in shares)


def _recency_bias_score(
    executions: Sequence[IBKRExecution],
    market_prices: dict[str, float] | None = None,
) -> float | None:
    """Fraction of BUY executions within 5% of that symbol's recent high.

    Requires market_prices dict {symbol: current_price}. Without it returns None.
    """
    if not market_prices:
        return None
    buys = [ex for ex in executions if ex.side == "BUY"]
    if not buys:
        return None
    chasing_count = 0
    for ex in buys:
        recent_high = market_prices.get(ex.symbol)
        if recent_high is None:
            continue
        if float(ex.price) >= recent_high * 0.95:
            chasing_count += 1
    return chasing_count / len(buys)


# ── behavioral flag detection ─────────────────────────────────────────────────


def _detect_flags(
    win_rate_val: float | None,
    disposition_score: float | None,
    concentration: float | None,
    profit_factor_val: float | None,
) -> list[str]:
    flags: list[str] = []
    if win_rate_val is not None and win_rate_val < 0.40:
        flags.append("LOW_WIN_RATE")
    if disposition_score is not None and disposition_score > 0.30:
        flags.append("DISPOSITION_EFFECT")
    if concentration is not None and concentration > 0.50:
        flags.append("HIGH_CONCENTRATION")
    if profit_factor_val is not None and profit_factor_val < 1.0:
        flags.append("NEGATIVE_EXPECTANCY")
    return flags


# ── per-symbol stats ──────────────────────────────────────────────────────────


def _per_symbol_stats(
    executions: Sequence[IBKRExecution],
    pairs: list[TradePair],
) -> dict[str, object]:
    pairs_by_symbol: dict[str, list[TradePair]] = defaultdict(list)
    for p in pairs:
        pairs_by_symbol[p.symbol].append(p)

    count_by_symbol: dict[str, int] = defaultdict(int)
    for ex in executions:
        count_by_symbol[ex.symbol] += 1

    result: dict[str, object] = {}
    for symbol, sym_pairs in pairs_by_symbol.items():
        result[symbol] = {
            "executions": count_by_symbol[symbol],
            "completed_trades": len(sym_pairs),
            "win_rate": _win_rate(sym_pairs),
            "avg_winner_pct": _avg_winner_pct(sym_pairs),
            "avg_loser_pct": _avg_loser_pct(sym_pairs),
            "avg_holding_days": _avg_holding_days(sym_pairs),
        }
    return result


# ── public entry point ────────────────────────────────────────────────────────


def build_trading_profile(
    executions: Sequence[IBKRExecution],
    period_months: int = 12,
    as_of_date: dt.date | None = None,
    market_prices: dict[str, float] | None = None,
) -> TradingProfile:
    """Compute deterministic trading profile from raw executions."""
    today = as_of_date or dt.date.today()
    profile = TradingProfile(period_months=period_months, as_of_date=today)

    if not executions:
        return profile

    profile.total_executions = len(executions)
    profile.total_symbols_traded = len({ex.symbol for ex in executions})

    pairs, open_qty = _fifo_match(executions)

    profile.win_rate = _win_rate(pairs)
    profile.avg_winner_pct = _avg_winner_pct(pairs)
    profile.avg_loser_pct = _avg_loser_pct(pairs)
    profile.profit_factor = _profit_factor(pairs)
    profile.avg_holding_days = _avg_holding_days(pairs)
    profile.disposition_effect_score = _disposition_effect_score(pairs)
    profile.concentration_score = _concentration_score(executions)
    profile.recency_bias_score = _recency_bias_score(executions, market_prices)

    profile.behavioral_flags = _detect_flags(
        profile.win_rate,
        profile.disposition_effect_score,
        profile.concentration_score,
        profile.profit_factor,
    )

    profile.per_symbol_stats = _per_symbol_stats(executions, pairs)
    profile.raw_metrics = {
        "completed_trade_pairs": len(pairs),
        "open_positions": {k: v for k, v in open_qty.items() if v > 0},
        "winner_count": sum(1 for p in pairs if p.is_winner),
        "loser_count": sum(1 for p in pairs if not p.is_winner),
    }

    return profile
