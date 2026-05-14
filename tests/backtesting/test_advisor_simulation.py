"""Unit + integration tests for packages/backtesting/advisor_simulation.py.

Pure-state tests are synchronous (no DB).
DB-bound tests use the shared ``db_session`` fixture.
"""

from __future__ import annotations

import datetime as dt
import uuid

import pytest
from backtesting.advisor_simulation import (
    _find_price,
    _latest_price_on_or_before,
    _Position,
    _SimState,
    run_advisor_backtest,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _bars(symbol: str, start: dt.date, n: int, start_price: float = 100.0, dr: float = 0.0) -> dict[str, dict[dt.date, float]]:
    """Build a minimal bars_by_symbol dict."""
    prices: dict[dt.date, float] = {}
    price = start_price
    d = start
    for _ in range(n):
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        prices[d] = round(price, 4)
        price *= 1 + dr
        d += dt.timedelta(days=1)
    return {symbol.upper(): prices}


async def _seed_market_bars(
    db_session,
    symbol: str,
    start: dt.date,
    n: int = 60,
    start_price: float = 100.0,
    dr: float = 0.003,
) -> None:
    from db.models import MarketPrice

    price = start_price
    d = start
    rows = []
    for _ in range(n):
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        rows.append(MarketPrice(
            symbol=symbol.upper(), price_date=d,
            open=round(price, 4), high=round(price * 1.005, 4),
            low=round(price * 0.995, 4), close=round(price, 4),
            adjusted_close=round(price, 4), volume=1_000_000, provider="yfinance",
        ))
        price *= 1 + dr
        d += dt.timedelta(days=1)
    db_session.add_all(rows)
    await db_session.flush()


async def _seed_completed_run_with_rec(
    db_session,
    user_id: uuid.UUID,
    symbol: str,
    action: str,
    rec_date: dt.date,
    price: float = 100.0,
) -> tuple:
    """Return (run, neutral_rec) seeded in DB."""
    from db.enums import ResearchRunStatus, ResearchRunType
    from db.models import NeutralRecommendation, ResearchRun

    run = ResearchRun(
        user_id=user_id,
        run_type=ResearchRunType.MANUAL.value,
        status=ResearchRunStatus.COMPLETED.value,
        started_at=dt.datetime.combine(rec_date, dt.time(9, 0), tzinfo=dt.UTC),
        finished_at=dt.datetime.combine(rec_date, dt.time(10, 0), tzinfo=dt.UTC),
    )
    db_session.add(run)
    await db_session.flush()

    rec_dt = dt.datetime.combine(rec_date, dt.time(10, 0), tzinfo=dt.UTC)
    nr = NeutralRecommendation(
        research_run_id=run.id,
        symbol=symbol,
        action=action,
        score=70,
        confidence=0.75,
        final_reason="Test",
        score_breakdown_json={},
        main_reasons_json=[],
        main_risks_json=[],
        missing_details_json=[],
        what_changed_json=[],
        as_of_time=rec_dt,
        price_at_recommendation=price,
    )
    # Override created_at so date-based filtering works
    nr.created_at = rec_dt  # type: ignore[assignment]
    db_session.add(nr)
    await db_session.flush()
    return run, nr


# ── Pure-state tests ──────────────────────────────────────────────────────────


def test_position_update_buy_tracks_avg_cost() -> None:
    pos = _Position("AAPL")
    pos.update_buy(10, 100.0)
    assert pos.qty == 10.0
    assert pos.avg_cost == 100.0
    pos.update_buy(10, 120.0)
    assert pos.qty == 20.0
    assert pos.avg_cost == 110.0  # (100*10 + 120*10) / 20


def test_sim_state_equity_cash_only() -> None:
    state = _SimState(cash=10_000.0)
    assert state.equity({}) == 10_000.0


def test_sim_state_equity_with_position() -> None:
    state = _SimState(cash=9_000.0)
    state.positions["AAPL"] = _Position("AAPL", qty=10.0, avg_cost=100.0)
    assert state.equity({"AAPL": 110.0}) == 10_100.0


def test_sim_state_position_weight() -> None:
    state = _SimState(cash=9_000.0)
    state.positions["AAPL"] = _Position("AAPL", qty=10.0, avg_cost=100.0)
    w = state.position_weight("AAPL", {"AAPL": 100.0})
    assert abs(w - 0.1) < 0.001


def test_drawdown_tracked() -> None:
    state = _SimState(cash=10_000.0)
    state.peak_equity = 10_000.0
    dd1 = state.update_drawdown(9_000.0)
    assert abs(dd1 - (-0.1)) < 1e-6
    assert abs(state.max_drawdown - (-0.1)) < 1e-6
    dd2 = state.update_drawdown(11_000.0)
    assert dd2 == 0.0
    assert abs(state.max_drawdown - (-0.1)) < 1e-6   # max_drawdown unchanged


def test_find_price_exact_date() -> None:
    start = dt.date(2024, 1, 2)
    b = _bars("AAPL", start, 5, start_price=100.0)
    price, actual = _find_price(start, b, "AAPL")
    assert price == 100.0
    assert actual == start


def test_find_price_forward_skip_weekend() -> None:
    # Put a price on a Wednesday, look up a Monday
    mon = dt.date(2024, 1, 8)   # Monday
    wed = dt.date(2024, 1, 10)  # Wednesday
    b: dict[str, dict[dt.date, float]] = {"AAPL": {wed: 105.0}}
    price, actual = _find_price(mon, b, "AAPL", forward_only=True, tolerance=5)
    assert price == 105.0
    assert actual == wed


def test_find_price_missing_returns_none() -> None:
    b: dict[str, dict[dt.date, float]] = {"AAPL": {}}
    price, actual = _find_price(dt.date(2024, 1, 2), b, "AAPL")
    assert price is None
    assert actual is None


def test_latest_price_on_or_before() -> None:
    b: dict[str, dict[dt.date, float]] = {
        "AAPL": {
            dt.date(2024, 1, 2): 100.0,
            dt.date(2024, 1, 3): 101.0,
            dt.date(2024, 1, 4): 102.0,
        }
    }
    price = _latest_price_on_or_before(dt.date(2024, 1, 3), b, "AAPL")
    assert price == 101.0
    # Date after last bar
    price2 = _latest_price_on_or_before(dt.date(2024, 1, 10), b, "AAPL")
    assert price2 == 102.0


# ── DB-bound simulation tests ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buy_creates_position_and_reduces_cash(db_session) -> None:
    """BUY_CANDIDATE creates a position and cash decreases."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)

    _, nr = await _seed_completed_run_with_rec(
        db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start
    )

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    assert run.status == "COMPLETED"
    # BUY_CANDIDATE → target weight 10 % → ~$1000 in AAPL
    buys = [t for t in run.trades if t.trade_type == "BUY"]
    assert len(buys) == 1
    assert run.cash_final is not None
    assert float(run.cash_final) < 10_000.0


@pytest.mark.asyncio
async def test_hold_creates_no_trade(db_session) -> None:
    """HOLD recommendation generates a SKIP trade, no BUY/SELL."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "HOLD", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session, user_id=uid,
        start_date=start, end_date=end, initial_cash=10_000.0,
    )

    real_trades = [t for t in run.trades if t.trade_type != "SKIP"]
    assert len(real_trades) == 0
    assert float(run.cash_final) == pytest.approx(10_000.0, rel=1e-4)


@pytest.mark.asyncio
async def test_buy_at_target_weight_skips(db_session) -> None:
    """Second BUY_CANDIDATE for a symbol already at target weight is skipped."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 5, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=90)

    # Two recs on consecutive days — second should be skipped
    _, nr1 = await _seed_completed_run_with_rec(
        db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start
    )
    _, nr2 = await _seed_completed_run_with_rec(
        db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start + dt.timedelta(days=1)
    )

    run = await run_advisor_backtest(
        session=db_session, user_id=uid,
        start_date=start, end_date=end, initial_cash=10_000.0,
    )

    buys = [t for t in run.trades if t.trade_type == "BUY"]
    skips = [t for t in run.trades if t.trade_type == "SKIP" and t.reason == "already_at_or_above_target"]
    assert len(buys) == 1
    assert len(skips) >= 1


@pytest.mark.asyncio
async def test_reduce_sells_half_position(db_session) -> None:
    """REDUCE sells 50 % of existing position."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 5, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=90)

    d1 = start
    d2 = start + dt.timedelta(days=3)

    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=d1)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "REDUCE", rec_date=d2)

    run = await run_advisor_backtest(
        session=db_session, user_id=uid,
        start_date=start, end_date=end, initial_cash=10_000.0,
    )

    reduces = [t for t in run.trades if t.trade_type == "REDUCE"]
    buys = [t for t in run.trades if t.trade_type == "BUY"]
    assert len(reduces) == 1
    assert len(buys) == 1
    b = buys[0]
    r = reduces[0]
    # REDUCE qty should be ~half of BUY qty
    assert b.quantity is not None and r.quantity is not None
    assert abs(float(r.quantity) - float(b.quantity) * 0.5) < 0.01


@pytest.mark.asyncio
async def test_sell_closes_position(db_session) -> None:
    """SELL after BUY closes position fully (position_after == 0)."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 5, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=90)

    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)
    await _seed_completed_run_with_rec(
        db_session, uid, "AAPL", "SELL", rec_date=start + dt.timedelta(days=5)
    )

    run = await run_advisor_backtest(
        session=db_session, user_id=uid,
        start_date=start, end_date=end, initial_cash=10_000.0,
    )

    sells = [t for t in run.trades if t.trade_type == "SELL"]
    assert len(sells) == 1
    assert float(sells[0].position_after) == 0.0


@pytest.mark.asyncio
async def test_missing_price_creates_skip_no_crash(db_session) -> None:
    """If no price bars exist for a symbol, rec is SKIP with missing_execution_price."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)
    # No market bars seeded for TSLA
    await _seed_completed_run_with_rec(db_session, uid, "TSLA", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session, user_id=uid,
        start_date=start, end_date=end, initial_cash=10_000.0,
    )

    # No price bars for TSLA → equity curve is empty → INSUFFICIENT_DATA is valid too
    assert run.status in ("COMPLETED", "INSUFFICIENT_DATA")
    skips = [t for t in run.trades if t.reason == "missing_execution_price"]
    assert len(skips) == 1
    assert float(run.cash_final) == pytest.approx(10_000.0, rel=1e-4)


@pytest.mark.asyncio
async def test_equity_curve_final_equity_reflects_positions(db_session) -> None:
    """Final equity row in equity_points reflects cash + positions."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session, user_id=uid,
        start_date=start, end_date=end, initial_cash=10_000.0,
    )

    assert len(run.equity_points) > 0
    last_ep = max(run.equity_points, key=lambda e: e.date)
    # equity ≈ cash + positions_value
    total = float(last_ep.cash) + float(last_ep.positions_value)
    assert abs(total - float(last_ep.equity)) < 1.0


@pytest.mark.asyncio
async def test_max_drawdown_computed(db_session) -> None:
    """Max drawdown is negative when price falls after buy."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    # Seed declining price bars
    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=-0.005)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session, user_id=uid,
        start_date=start, end_date=end, initial_cash=10_000.0,
    )

    assert run.max_drawdown_pct is not None
    assert float(run.max_drawdown_pct) <= 0.0


@pytest.mark.asyncio
async def test_benchmark_return_computed_when_spy_exists(db_session) -> None:
    """When SPY bars exist, benchmark_return_pct is populated."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_market_bars(db_session, "SPY", start - dt.timedelta(days=5), n=60, start_price=400.0, dr=0.001)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session, user_id=uid,
        start_date=start, end_date=end, initial_cash=10_000.0, benchmark_symbol="SPY",
    )

    assert run.benchmark_return_pct is not None
    assert run.relative_return_pct is not None


@pytest.mark.asyncio
async def test_missing_benchmark_does_not_fail_run(db_session) -> None:
    """Missing SPY bars produce null benchmark fields, not a crash."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    # No SPY bars
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session, user_id=uid,
        start_date=start, end_date=end, initial_cash=10_000.0, benchmark_symbol="SPY",
    )

    assert run.status == "COMPLETED"
    assert run.benchmark_return_pct is None
    assert run.relative_return_pct is None


@pytest.mark.asyncio
async def test_no_recommendations_creates_cash_only_run(db_session) -> None:
    """With no recs in range, run completes with no trades and final_equity == initial_cash."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start, n=30)

    run = await run_advisor_backtest(
        session=db_session, user_id=uid,
        start_date=start, end_date=end, initial_cash=10_000.0,
    )

    assert run.status == "COMPLETED"
    assert run.total_trades == 0
    assert float(run.final_equity) == pytest.approx(10_000.0, rel=1e-4)


@pytest.mark.asyncio
async def test_user_a_recs_not_used_for_user_b(db_session) -> None:
    """User A's runs must never appear in User B's simulation."""
    uid_a = uuid.uuid4()
    uid_b = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    # Only User A has a completed run with a BUY rec
    await _seed_completed_run_with_rec(db_session, uid_a, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run_b = await run_advisor_backtest(
        session=db_session, user_id=uid_b,
        start_date=start, end_date=end, initial_cash=10_000.0,
    )

    # User B must have no real trades
    real_trades_b = [t for t in run_b.trades if t.trade_type != "SKIP"]
    assert len(real_trades_b) == 0


@pytest.mark.asyncio
async def test_summary_json_fields(db_session) -> None:
    """summary_json contains required fields including human_summary."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session, user_id=uid,
        start_date=start, end_date=end, initial_cash=10_000.0,
    )

    s = run.summary_json
    for key in ("initial_cash", "final_equity", "profit_loss_amount",
                "total_return_pct", "human_summary", "skipped_recommendations"):
        assert key in s, f"Missing key: {key}"
    assert "$10,000.00" in s["human_summary"]
