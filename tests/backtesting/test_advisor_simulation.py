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
    _fmt_currency,
    _fmt_relative_pp,
    _fmt_signed_currency,
    _fmt_signed_pct,
    _latest_price_on_or_before,
    _Position,
    _replay_apply_executed_trade,
    _SimState,
    run_advisor_backtest,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _bars(
    symbol: str, start: dt.date, n: int, start_price: float = 100.0, dr: float = 0.0
) -> dict[str, dict[dt.date, float]]:
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
        rows.append(
            MarketPrice(
                symbol=symbol.upper(),
                price_date=d,
                open=round(price, 4),
                high=round(price * 1.005, 4),
                low=round(price * 0.995, 4),
                close=round(price, 4),
                adjusted_close=round(price, 4),
                volume=1_000_000,
                provider="yfinance",
            )
        )
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
    metadata: dict | None = None,
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
        metadata_json=metadata or {},
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
    assert abs(state.max_drawdown - (-0.1)) < 1e-6  # max_drawdown unchanged


def test_find_price_exact_date() -> None:
    start = dt.date(2024, 1, 2)
    b = _bars("AAPL", start, 5, start_price=100.0)
    price, actual = _find_price(start, b, "AAPL")
    assert price == 100.0
    assert actual == start


def test_find_price_forward_skip_weekend() -> None:
    # Put a price on a Wednesday, look up a Monday
    mon = dt.date(2024, 1, 8)  # Monday
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


def test_replay_apply_buy_then_reduce_matches_direct_state() -> None:
    """Replay helper builds same qty/cash as sequential BUY + REDUCE rows."""
    row_buy = {
        "symbol": "AAPL",
        "trade_type": "BUY",
        "cash_delta": -500.0,
        "quantity": 5.0,
        "price": 100.0,
        "position_after": None,
    }
    row_reduce = {
        "symbol": "AAPL",
        "trade_type": "REDUCE",
        "cash_delta": 250.0,
        "quantity": 2.5,
        "price": 100.0,
        "position_after": 2.5,
    }
    st = _SimState(cash=10_000.0)
    _replay_apply_executed_trade(st, row_buy)
    _replay_apply_executed_trade(st, row_reduce)
    assert st.cash == pytest.approx(9750.0)
    assert st.positions["AAPL"].qty == pytest.approx(2.5)


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
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
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
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    buys = [t for t in run.trades if t.trade_type == "BUY"]
    skips = [
        t for t in run.trades if t.trade_type == "SKIP" and t.reason == "already_at_or_above_target"
    ]
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
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
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
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
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
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
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
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
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
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
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
    await _seed_market_bars(
        db_session, "SPY", start - dt.timedelta(days=5), n=60, start_price=400.0, dr=0.001
    )
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
        benchmark_symbol="SPY",
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
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
        benchmark_symbol="SPY",
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
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
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
        session=db_session,
        user_id=uid_b,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    # User B must have no real trades
    real_trades_b = [t for t in run_b.trades if t.trade_type != "SKIP"]
    assert len(real_trades_b) == 0


@pytest.mark.asyncio
async def test_equity_curve_no_lookahead_before_first_buy(db_session) -> None:
    """Positions and reduced cash appear only on/after the first BUY execution date."""
    uid = uuid.uuid4()
    buy_rec = dt.date(2026, 1, 15)
    start = dt.date(2026, 1, 2)
    end = dt.date(2026, 2, 28)

    await _seed_market_bars(
        db_session, "AAPL", start - dt.timedelta(days=5), n=80, start_price=100.0, dr=0.0
    )
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=buy_rec)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    buys = [t for t in run.trades if t.trade_type == "BUY"]
    assert len(buys) == 1
    exec_d = buys[0].trade_date.date()

    for ep in run.equity_points:
        if ep.date < exec_d:
            assert float(ep.cash) == pytest.approx(10_000.0, rel=1e-4)
            assert float(ep.positions_value) == pytest.approx(0.0, abs=0.02)

    after = [ep for ep in run.equity_points if ep.date >= exec_d]
    assert after, "expected at least one equity point on/after buy execution"
    assert float(min(after, key=lambda e: e.date).positions_value) > 0.0


@pytest.mark.asyncio
async def test_final_equity_and_cash_match_last_equity_point(db_session) -> None:
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    assert run.equity_points
    last_ep = max(run.equity_points, key=lambda e: e.date)
    assert float(run.final_equity) == pytest.approx(float(last_ep.equity), rel=1e-4)
    assert float(run.cash_final) == pytest.approx(float(last_ep.cash), rel=1e-4)
    tr = (float(run.final_equity) - 10_000.0) / 10_000.0
    assert float(run.total_return_pct) == pytest.approx(tr, rel=1e-4)


@pytest.mark.asyncio
async def test_reduce_hits_position_only_from_reduce_execution_date(db_session) -> None:
    """REDUCE lowers MTM position value from the reduce execution date onward."""
    uid = uuid.uuid4()
    d_buy = dt.date(2026, 1, 10)
    d_reduce = dt.date(2026, 1, 20)
    start = dt.date(2026, 1, 2)
    end = dt.date(2026, 2, 15)

    await _seed_market_bars(
        db_session, "AAPL", start - dt.timedelta(days=5), n=80, start_price=100.0, dr=0.0
    )
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=d_buy)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "REDUCE", rec_date=d_reduce)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    reduces = [t for t in run.trades if t.trade_type == "REDUCE"]
    assert len(reduces) == 1
    exec_red = reduces[0].trade_date.date()

    pts_before = [ep for ep in run.equity_points if ep.date < exec_red]
    pts_from_red = [ep for ep in run.equity_points if ep.date >= exec_red]
    assert pts_before and pts_from_red
    pos_before_max = max(float(ep.positions_value) for ep in pts_before)
    pos_at_red = float(min(pts_from_red, key=lambda e: e.date).positions_value)
    assert pos_before_max > 0.0
    assert pos_at_red > 0.0
    assert pos_at_red < pos_before_max * 0.75


# ── M11.4 named regression tests — lookahead-bias guardrails ─────────────────


@pytest.mark.asyncio
async def test_no_lookahead_before_first_buy(db_session) -> None:
    """All equity points before the first BUY execution date have cash=initial_cash, pos=0."""
    uid = uuid.uuid4()
    # Recommendation on Jan 15; simulation starts Jan 2
    buy_date = dt.date(2026, 1, 15)
    start = dt.date(2026, 1, 2)
    end = dt.date(2026, 2, 28)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=80, dr=0.0)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=buy_date)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    buys = [t for t in run.trades if t.trade_type == "BUY"]
    assert len(buys) == 1
    exec_d = buys[0].trade_date.date()

    # Every equity point strictly before the execution date must show the initial state.
    pre_trade = [ep for ep in run.equity_points if ep.date < exec_d]
    assert pre_trade, "expected equity points before the buy date"
    for ep in pre_trade:
        assert float(ep.cash) == pytest.approx(10_000.0, rel=1e-4), (
            f"cash should be initial_cash before first BUY; got {ep.cash} on {ep.date}"
        )
        assert float(ep.positions_value) == pytest.approx(0.0, abs=0.02), (
            f"positions_value should be 0 before first BUY; got {ep.positions_value} on {ep.date}"
        )
        assert float(ep.equity) == pytest.approx(10_000.0, rel=1e-4), (
            f"equity should equal initial_cash before first BUY; got {ep.equity} on {ep.date}"
        )


@pytest.mark.asyncio
async def test_buy_affects_equity_from_trade_date_onward(db_session) -> None:
    """Cash decreases and positions_value > 0 only on/after the BUY execution date."""
    uid = uuid.uuid4()
    buy_date = dt.date(2026, 1, 15)
    start = dt.date(2026, 1, 2)
    end = dt.date(2026, 2, 28)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=80, dr=0.0)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=buy_date)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    buys = [t for t in run.trades if t.trade_type == "BUY"]
    assert len(buys) == 1
    exec_d = buys[0].trade_date.date()

    first_on_or_after = min(
        (ep for ep in run.equity_points if ep.date >= exec_d),
        key=lambda e: e.date,
    )
    assert float(first_on_or_after.cash) < 10_000.0, "cash must decrease after BUY"
    assert float(first_on_or_after.positions_value) > 0.0, "positions_value must be > 0 after BUY"


@pytest.mark.asyncio
async def test_reduce_or_sell_affects_only_from_trade_date(db_session) -> None:
    """SELL closes position: all equity points before SELL show original qty; after shows 0."""
    uid = uuid.uuid4()
    d_buy = dt.date(2026, 1, 10)
    d_sell = dt.date(2026, 1, 25)
    start = dt.date(2026, 1, 2)
    end = dt.date(2026, 2, 15)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=80, dr=0.0)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=d_buy)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "SELL", rec_date=d_sell)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    sells = [t for t in run.trades if t.trade_type == "SELL"]
    assert len(sells) == 1
    exec_sell_d = sells[0].trade_date.date()

    buys = [t for t in run.trades if t.trade_type == "BUY"]
    exec_buy_d = buys[0].trade_date.date()

    # Between BUY and SELL, positions_value > 0
    between = [ep for ep in run.equity_points if exec_buy_d <= ep.date < exec_sell_d]
    assert between, "expected equity points between buy and sell"
    for ep in between:
        assert float(ep.positions_value) > 0.0, (
            f"positions_value should be > 0 between BUY and SELL; got {ep.positions_value} on {ep.date}"
        )

    # On/after SELL date, positions_value should be 0 (full position sold)
    after_sell = [ep for ep in run.equity_points if ep.date >= exec_sell_d]
    assert after_sell, "expected equity points after sell"
    for ep in after_sell:
        assert float(ep.positions_value) == pytest.approx(0.0, abs=0.02), (
            f"positions_value should be 0 after SELL; got {ep.positions_value} on {ep.date}"
        )

    # After SELL, cash should be roughly back near initial_cash (flat price scenario)
    last_ep = max(after_sell, key=lambda e: e.date)
    assert float(last_ep.cash) == pytest.approx(10_000.0, rel=0.02)


@pytest.mark.asyncio
async def test_final_equity_equals_last_equity_point(db_session) -> None:
    """run.final_equity must exactly equal the last equity_point.equity."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=0.002)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    assert run.equity_points
    last_ep = max(run.equity_points, key=lambda e: e.date)
    assert float(run.final_equity) == pytest.approx(float(last_ep.equity), rel=1e-5), (
        f"final_equity={run.final_equity} != last equity_point.equity={last_ep.equity}"
    )


@pytest.mark.asyncio
async def test_total_return_uses_last_equity(db_session) -> None:
    """total_return_pct must equal (last_equity_point.equity - initial_cash) / initial_cash."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)
    initial_cash = 10_000.0

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=0.002)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=initial_cash,
    )

    last_ep = max(run.equity_points, key=lambda e: e.date)
    expected_tr = (float(last_ep.equity) - initial_cash) / initial_cash
    assert float(run.total_return_pct) == pytest.approx(expected_tr, rel=1e-5)


@pytest.mark.asyncio
async def test_max_drawdown_from_chronological_curve(db_session) -> None:
    """Max drawdown is based on the chronological equity curve (not final equity state).

    Price rises 1 %/day for 20 bars then falls 2 %/day for 20 bars.
    The max drawdown should reflect the peak-to-trough in the *chronological* curve.
    A lookahead implementation (apply final state everywhere) would compute the wrong peak.
    """
    from db.models import MarketPrice

    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 5, 30)
    initial_cash = 10_000.0

    # Seed bars: buffer (flat), then 20 up days, then 20 down days
    price = 100.0
    d = start - dt.timedelta(days=5)
    rows = []
    bar_idx = 0
    while bar_idx < 50:
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        rows.append(
            MarketPrice(
                symbol="AAPL",
                price_date=d,
                open=round(price, 6),
                high=round(price * 1.002, 6),
                low=round(price * 0.998, 6),
                close=round(price, 6),
                adjusted_close=round(price, 6),
                volume=1_000_000,
                provider="yfinance",
            )
        )
        # Buffer bars (first 5): flat. Then 20 bars up, then 20 down.
        if bar_idx < 5:
            pass  # flat
        elif bar_idx < 25:
            price *= 1.01  # rise 1 %/day
        else:
            price *= 0.98  # fall 2 %/day
        bar_idx += 1
        d += dt.timedelta(days=1)
    db_session.add_all(rows)
    await db_session.flush()

    # BUY on the first trading day (bar_idx=5 = start), price = 100.0
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=initial_cash,
    )

    assert run.max_drawdown_pct is not None
    max_dd = float(run.max_drawdown_pct)

    # Price peaked somewhere in the rising phase, then fell.
    # With only the portfolio's 10 % weight in AAPL, the portfolio drawdown is roughly
    # 10 % of the price drawdown. With 2 %/day falls over ~20 bars the price falls ~33 %,
    # producing a portfolio drawdown of ~3-5 %. Verify a meaningful non-trivial drawdown.
    assert max_dd < -0.02, f"expected max_drawdown < -2 %; got {max_dd:.4f}"

    # It must also be computed from the chronological curve, not from a final-state shortcut.
    # Verify the last equity point has lower equity than the peak in the curve.
    eps_sorted = sorted(run.equity_points, key=lambda e: e.date)
    peak_equity = max(float(ep.equity) for ep in eps_sorted)
    last_equity = float(eps_sorted[-1].equity)
    assert last_equity < peak_equity, "final equity should be below peak (price falls at end)"
    # The reported drawdown should match the worst point.
    expected_worst = min(
        (float(ep.equity) - peak_equity) / peak_equity
        for ep in eps_sorted
        if float(ep.equity) <= peak_equity
    )
    assert abs(max_dd - expected_worst) < 0.005, (
        f"max_drawdown_pct={max_dd:.6f} deviates too much from worst-point drawdown {expected_worst:.6f}"
    )


@pytest.mark.asyncio
async def test_summary_json_fields(db_session) -> None:
    """summary_json contains required fields including human_summary."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    s = run.summary_json
    for key in (
        "initial_cash",
        "final_equity",
        "profit_loss_amount",
        "total_return_pct",
        "human_summary",
        "skipped_recommendations",
    ):
        assert key in s, f"Missing key: {key}"
    assert "$10,000.00" in s["human_summary"]


# ── M11.5 enriched summary tests ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_summary_json_includes_trade_and_skip_breakdown(db_session) -> None:
    """trade_breakdown counts every trade_type; skip_breakdown counts by reason."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=0.0)
    # BUY on day 1, HOLD (skip) on day 5
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)
    await _seed_completed_run_with_rec(
        db_session, uid, "AAPL", "HOLD", rec_date=start + dt.timedelta(days=5)
    )

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    s = run.summary_json
    assert "trade_breakdown" in s
    assert "skip_breakdown" in s

    tb = s["trade_breakdown"]
    assert tb.get("BUY") == 1
    assert tb.get("SKIP", 0) >= 1

    sb = s["skip_breakdown"]
    # HOLD generates a "hold_or_no_action" skip reason
    assert sb.get("hold_or_no_action", 0) >= 1


@pytest.mark.asyncio
async def test_summary_json_final_cash_and_positions_match_last_equity_point(db_session) -> None:
    """summary_json.final_cash and final_positions_value match last equity_point."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=0.002)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    last_ep = max(run.equity_points, key=lambda e: e.date)
    s = run.summary_json

    assert abs(s["final_cash"] - float(last_ep.cash)) < 0.01
    assert abs(s["final_positions_value"] - float(last_ep.positions_value)) < 0.01


@pytest.mark.asyncio
async def test_summary_json_open_positions_after_buy_and_reduce(db_session) -> None:
    """open_positions contains the partially-reduced position at end."""
    uid = uuid.uuid4()
    d_buy = dt.date(2024, 3, 1)
    d_reduce = dt.date(2024, 3, 15)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", d_buy - dt.timedelta(days=5), n=70, dr=0.0)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=d_buy)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "REDUCE", rec_date=d_reduce)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=d_buy,
        end_date=end,
        initial_cash=10_000.0,
    )

    s = run.summary_json
    assert "open_positions" in s
    op = s["open_positions"]
    assert len(op) == 1, "one symbol should remain partially open after REDUCE"
    pos = op[0]
    assert pos["symbol"] == "AAPL"
    assert pos["quantity"] > 0.0
    assert pos["avg_cost"] > 0.0
    assert pos["market_value"] > 0.0
    assert "unrealized_pnl" in pos
    assert "weight" in pos
    assert "last_price" in pos

    # top_open_position should point to the same AAPL entry
    assert s["top_open_position"] is not None
    assert s["top_open_position"]["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_summary_json_closed_positions_after_sell(db_session) -> None:
    """closed_positions contains the SELL trade with realized_pnl."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    d_sell = start + dt.timedelta(days=7)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=70, dr=0.0)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "SELL", rec_date=d_sell)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    s = run.summary_json
    assert "closed_positions" in s
    cp = s["closed_positions"]
    assert len(cp) == 1
    c = cp[0]
    assert c["symbol"] == "AAPL"
    assert c["trade_type"] == "SELL"
    assert c["quantity"] > 0.0
    assert c["entry_avg_cost"] is not None
    assert c["exit_price"] > 0.0
    assert c["realized_pnl"] is not None
    # flat price → realized_pnl should be ≈ 0
    assert abs(c["realized_pnl"]) < 1.0

    # no open positions remain
    assert s["open_positions"] == []
    assert s["top_open_position"] is None


@pytest.mark.asyncio
async def test_summary_json_best_and_worst_realized_trade(db_session) -> None:
    """best/worst realized trade fields reflect highest and lowest realized_pnl."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 5, 30)

    # Rising price: AAPL winner, flat price: NVDA breakeven
    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=90, dr=0.005)
    await _seed_market_bars(db_session, "NVDA", start - dt.timedelta(days=5), n=90, dr=0.0)

    d_buy1 = start
    d_sell1 = start + dt.timedelta(days=20)
    d_buy2 = start + dt.timedelta(days=5)
    d_sell2 = start + dt.timedelta(days=25)

    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=d_buy1)
    await _seed_completed_run_with_rec(db_session, uid, "NVDA", "BUY_CANDIDATE", rec_date=d_buy2)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "SELL", rec_date=d_sell1)
    await _seed_completed_run_with_rec(db_session, uid, "NVDA", "SELL", rec_date=d_sell2)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
    )

    s = run.summary_json
    assert s["best_realized_trade"] is not None
    assert s["worst_realized_trade"] is not None
    best = s["best_realized_trade"]
    worst = s["worst_realized_trade"]
    assert best["realized_pnl"] >= worst["realized_pnl"]

    # AAPL has rising price → winner; NVDA flat → roughly breakeven / smaller
    assert best["symbol"] == "AAPL"


@pytest.mark.asyncio
async def test_summary_json_benchmark_summary_with_spy(db_session) -> None:
    """benchmark_summary is populated when SPY bars exist."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=0.003)
    await _seed_market_bars(
        db_session, "SPY", start - dt.timedelta(days=5), n=60, start_price=400.0, dr=0.001
    )
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
        benchmark_symbol="SPY",
    )

    s = run.summary_json
    assert "benchmark_summary" in s
    bs = s["benchmark_summary"]
    assert bs["benchmark_symbol"] == "SPY"
    assert bs["benchmark_return_pct"] is not None
    assert bs["relative_return_pct"] is not None
    assert isinstance(bs["outperformed_benchmark"], bool)


@pytest.mark.asyncio
async def test_summary_json_benchmark_summary_no_spy_graceful(db_session) -> None:
    """benchmark_summary is present but null when SPY bars are missing."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
        benchmark_symbol="SPY",
    )

    s = run.summary_json
    assert "benchmark_summary" in s
    bs = s["benchmark_summary"]
    assert bs["benchmark_symbol"] == "SPY"
    assert bs["benchmark_return_pct"] is None
    assert bs["relative_return_pct"] is None
    assert bs["outperformed_benchmark"] is None


@pytest.mark.asyncio
async def test_summary_json_display_strings_format(db_session) -> None:
    """Display strings are deterministic and use correct formatting conventions."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=0.005)
    await _seed_market_bars(
        db_session, "SPY", start - dt.timedelta(days=5), n=60, start_price=400.0, dr=0.001
    )
    await _seed_completed_run_with_rec(db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
        benchmark_symbol="SPY",
    )

    s = run.summary_json

    # profit_loss_display — starts with "+" or "-" and contains "$"
    pld = s["profit_loss_display"]
    assert pld[0] in ("+", "-"), f"profit_loss_display should be signed: {pld!r}"
    assert "$" in pld

    # total_return_display — ends with "%"
    assert s["total_return_display"].endswith("%")

    # relative_return_display — contains "percentage points"
    assert "percentage points" in s["relative_return_display"]

    # max_drawdown_display — ends with "%"
    assert s["max_drawdown_display"].endswith("%")

    # final_cash_display — starts with "$"
    assert s["final_cash_display"].startswith("$")

    # verify formatting helpers directly (unit test)
    assert _fmt_currency(12543.53) == "$12,543.53"
    assert _fmt_signed_currency(2543.53) == "+$2,543.53"
    assert _fmt_signed_currency(-123.45) == "-$123.45"
    assert _fmt_signed_pct(0.2543) == "+25.43%"
    assert _fmt_signed_pct(-0.031) == "-3.10%"
    assert _fmt_relative_pp(0.1692) == "+16.92 percentage points"
    assert _fmt_relative_pp(None) == "N/A"


# ── M11.6 recommendation source filtering tests ───────────────────────────────

_SCENARIO_META = {"scenario_seed": True, "scenario": "test_scenario"}
_REAL_META: dict = {}  # no scenario_seed


@pytest.mark.asyncio
async def test_source_all_includes_both_scenario_and_real(db_session) -> None:
    """ALL (default) includes both scenario-seeded and real recommendations."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=0.0)
    await _seed_market_bars(db_session, "NVDA", start - dt.timedelta(days=5), n=60, dr=0.0)

    # One scenario rec + one real rec on different symbols
    await _seed_completed_run_with_rec(
        db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start, metadata=_SCENARIO_META
    )
    await _seed_completed_run_with_rec(
        db_session,
        uid,
        "NVDA",
        "BUY_CANDIDATE",
        rec_date=start + dt.timedelta(days=2),
        metadata=_REAL_META,
    )

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
        recommendation_source="ALL",
    )

    buys = [t for t in run.trades if t.trade_type == "BUY"]
    symbols_bought = {t.symbol for t in buys}
    assert "AAPL" in symbols_bought
    assert "NVDA" in symbols_bought
    assert run.summary_json["recommendations_considered"] == 2
    assert run.summary_json["recommendation_source"] == "ALL"


@pytest.mark.asyncio
async def test_source_scenario_includes_only_scenario_rows(db_session) -> None:
    """SCENARIO filters to only scenario_seed=True rows; real rows are excluded."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=0.0)
    await _seed_market_bars(db_session, "NVDA", start - dt.timedelta(days=5), n=60, dr=0.0)

    await _seed_completed_run_with_rec(
        db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start, metadata=_SCENARIO_META
    )
    await _seed_completed_run_with_rec(
        db_session,
        uid,
        "NVDA",
        "BUY_CANDIDATE",
        rec_date=start + dt.timedelta(days=2),
        metadata=_REAL_META,
    )

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
        recommendation_source="SCENARIO",
    )

    buys = [t for t in run.trades if t.trade_type == "BUY"]
    symbols_bought = {t.symbol for t in buys}
    assert "AAPL" in symbols_bought
    assert "NVDA" not in symbols_bought
    assert run.summary_json["recommendations_considered"] == 1
    assert run.summary_json["recommendation_source"] == "SCENARIO"
    assert run.summary_json["scenario_name"] is None


@pytest.mark.asyncio
async def test_source_scenario_with_scenario_name_filters_by_name(db_session) -> None:
    """SCENARIO + scenario_name includes only rows matching that scenario name."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=0.0)
    await _seed_market_bars(db_session, "NVDA", start - dt.timedelta(days=5), n=60, dr=0.0)
    await _seed_market_bars(db_session, "AMD", start - dt.timedelta(days=5), n=60, dr=0.0)

    # Two different scenario names
    meta_alpha = {"scenario_seed": True, "scenario": "alpha"}
    meta_beta = {"scenario_seed": True, "scenario": "beta"}

    await _seed_completed_run_with_rec(
        db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start, metadata=meta_alpha
    )
    await _seed_completed_run_with_rec(
        db_session,
        uid,
        "NVDA",
        "BUY_CANDIDATE",
        rec_date=start + dt.timedelta(days=2),
        metadata=meta_beta,
    )
    await _seed_completed_run_with_rec(
        db_session,
        uid,
        "AMD",
        "BUY_CANDIDATE",
        rec_date=start + dt.timedelta(days=4),
        metadata=meta_alpha,
    )

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
        recommendation_source="SCENARIO",
        scenario_name="alpha",
    )

    buys = [t for t in run.trades if t.trade_type == "BUY"]
    symbols_bought = {t.symbol for t in buys}
    assert "AAPL" in symbols_bought
    assert "AMD" in symbols_bought
    assert "NVDA" not in symbols_bought
    assert run.summary_json["recommendations_considered"] == 2
    assert run.summary_json["scenario_name"] == "alpha"


@pytest.mark.asyncio
async def test_source_real_excludes_scenario_rows(db_session) -> None:
    """REAL filters to only non-scenario rows; scenario_seed=True rows are excluded."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=0.0)
    await _seed_market_bars(db_session, "NVDA", start - dt.timedelta(days=5), n=60, dr=0.0)

    await _seed_completed_run_with_rec(
        db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start, metadata=_SCENARIO_META
    )
    await _seed_completed_run_with_rec(
        db_session,
        uid,
        "NVDA",
        "BUY_CANDIDATE",
        rec_date=start + dt.timedelta(days=2),
        metadata=_REAL_META,
    )

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
        recommendation_source="REAL",
    )

    buys = [t for t in run.trades if t.trade_type == "BUY"]
    symbols_bought = {t.symbol for t in buys}
    assert "NVDA" in symbols_bought
    assert "AAPL" not in symbols_bought
    assert run.summary_json["recommendations_considered"] == 1
    assert run.summary_json["recommendation_source"] == "REAL"


@pytest.mark.asyncio
async def test_source_scenario_no_matching_rows_graceful(db_session) -> None:
    """SCENARIO with no matching rows returns a graceful zero-trade run."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    # Only real recs — no scenario rows
    await _seed_completed_run_with_rec(
        db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start, metadata=_REAL_META
    )

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
        recommendation_source="SCENARIO",
    )

    assert run.status in ("COMPLETED", "INSUFFICIENT_DATA")
    assert run.total_trades == 0
    assert float(run.final_equity) == pytest.approx(10_000.0, rel=1e-4)
    assert run.summary_json["recommendations_considered"] == 0


@pytest.mark.asyncio
async def test_assumptions_json_stores_recommendation_source(db_session) -> None:
    """assumptions_json contains recommendation_source and scenario_name."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60)
    await _seed_completed_run_with_rec(
        db_session, uid, "AAPL", "BUY_CANDIDATE", rec_date=start, metadata=_SCENARIO_META
    )

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
        recommendation_source="SCENARIO",
        scenario_name="test_scenario",
    )

    a = run.assumptions_json
    assert a["recommendation_source"] == "SCENARIO"
    assert a["scenario_name"] == "test_scenario"


@pytest.mark.asyncio
async def test_summary_json_stores_source_and_recommendations_considered(db_session) -> None:
    """summary_json contains recommendation_source, scenario_name, recommendations_considered."""
    uid = uuid.uuid4()
    start = dt.date(2024, 3, 1)
    end = dt.date(2024, 4, 30)

    await _seed_market_bars(db_session, "AAPL", start - dt.timedelta(days=5), n=60, dr=0.0)
    await _seed_market_bars(db_session, "NVDA", start - dt.timedelta(days=5), n=60, dr=0.0)

    for sym, meta in [("AAPL", _SCENARIO_META), ("NVDA", _REAL_META)]:
        await _seed_completed_run_with_rec(
            db_session,
            uid,
            sym,
            "BUY_CANDIDATE",
            rec_date=start + dt.timedelta(days=1 if sym == "NVDA" else 0),
            metadata=meta,
        )

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
        recommendation_source="SCENARIO",
        scenario_name="test_scenario",
    )

    s = run.summary_json
    assert s["recommendation_source"] == "SCENARIO"
    assert s["scenario_name"] == "test_scenario"
    assert s["recommendations_considered"] == 1  # only AAPL passes SCENARIO + test_scenario filter


# ── initial_positions tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_initial_positions_seed_cash_reduced(db_session) -> None:
    """Seeding 10 shares @ $100 reduces opening cash by $1,000."""
    uid = uuid.uuid4()
    start = dt.date(2026, 1, 5)
    end = dt.date(2026, 1, 30)
    # dr=0.0 keeps price flat so final equity == initial_cash (cash + position)
    await _seed_market_bars(db_session, "AAPL", start, n=30, start_price=100.0, dr=0.0)

    run = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=10_000.0,
        initial_positions=[{"symbol": "AAPL", "quantity": 10}],
    )
    # final_equity = cash ($9,000) + position (10 * $100 = $1,000) = $10,000
    assert abs(run.final_equity - 10_000.0) < 0.01
    # cash_final must be less than initial_cash (position consumed $1,000)
    assert run.cash_final < 10_000.0


@pytest.mark.asyncio
async def test_initial_positions_reduce_creates_reduce_trade(db_session) -> None:
    """A REDUCE recommendation after seeded position produces a REDUCE trade, not a SKIP."""
    uid = uuid.uuid4()
    start = dt.date(2026, 1, 5)
    end = dt.date(2026, 2, 5)
    await _seed_market_bars(db_session, "AAPL", start, n=40, start_price=100.0)

    run, _ = await _seed_completed_run_with_rec(
        db_session,
        uid,
        "AAPL",
        "REDUCE",
        rec_date=dt.date(2026, 1, 12),
    )

    result = await run_advisor_backtest(
        session=db_session,
        user_id=uid,
        start_date=start,
        end_date=end,
        initial_cash=50_000.0,
        initial_positions=[{"symbol": "AAPL", "quantity": 100}],
    )
    reduce_trades = [t for t in result.trades if t.trade_type == "REDUCE"]
    skip_no_pos = [
        t for t in result.trades if t.trade_type == "SKIP" and t.reason == "no_position_to_reduce"
    ]
    assert len(reduce_trades) >= 1
    assert len(skip_no_pos) == 0


@pytest.mark.asyncio
async def test_initial_positions_unpriceable_raises_value_error(db_session) -> None:
    """Symbol with no market bars raises ValueError (not an exception crash)."""
    uid = uuid.uuid4()
    start = dt.date(2026, 1, 5)
    end = dt.date(2026, 1, 30)
    # No market data seeded for UNKNWN

    with pytest.raises(ValueError, match="Cannot price initial position UNKNWN"):
        await run_advisor_backtest(
            session=db_session,
            user_id=uid,
            start_date=start,
            end_date=end,
            initial_cash=10_000.0,
            initial_positions=[{"symbol": "UNKNWN", "quantity": 10}],
        )


@pytest.mark.asyncio
async def test_initial_positions_cost_exceeds_cash_raises_value_error(db_session) -> None:
    """Total cost > initial_cash raises ValueError."""
    uid = uuid.uuid4()
    start = dt.date(2026, 1, 5)
    end = dt.date(2026, 1, 30)
    await _seed_market_bars(db_session, "AAPL", start, n=30, start_price=100.0)

    with pytest.raises(ValueError, match="exceeds initial_cash"):
        await run_advisor_backtest(
            session=db_session,
            user_id=uid,
            start_date=start,
            end_date=end,
            initial_cash=500.0,  # $500 cash; 10 shares @ $100 = $1,000 cost
            initial_positions=[{"symbol": "AAPL", "quantity": 10}],
        )
