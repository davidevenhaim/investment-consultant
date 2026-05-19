"""Unit tests for backtesting.service — pure computation + DB-bound paths.

Pure compute tests are synchronous and require no DB.
DB-bound tests use the shared db_session fixture.
"""

from __future__ import annotations

import datetime as dt

import pytest
from backtesting.schemas import ForwardOutcome
from backtesting.service import (
    _classify_label,
    build_learning_event_fields,
    compute_forward_outcome,
    generate_learning_event_from_outcome,
    measure_recommendation_outcome,
    should_generate_learning_event,
)
from market_data.schemas import MarketPriceBar

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_bars(
    symbol: str,
    start_date: dt.date,
    n: int,
    start_price: float,
    daily_return: float = 0.001,
) -> list[MarketPriceBar]:
    bars = []
    price = start_price
    d = start_date
    for _ in range(n):
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        bars.append(
            MarketPriceBar(
                symbol=symbol,
                price_date=d,
                open=round(price, 4),
                high=round(price * 1.005, 4),
                low=round(price * 0.995, 4),
                close=round(price, 4),
                adjusted_close=round(price, 4),
                volume=1_000_000,
                provider="test",
            )
        )
        price *= 1 + daily_return
        d += dt.timedelta(days=1)
    return bars


def _make_drawdown_bars(
    symbol: str, start_date: dt.date, start_price: float
) -> list[MarketPriceBar]:
    """Bars that drop 15% mid-period then partially recover."""
    prices = [start_price]
    for _ in range(9):
        prices.append(prices[-1] * 0.98)  # -2% each day → ~-18% total
    for _ in range(11):
        prices.append(prices[-1] * 1.005)  # partial recovery

    bars = []
    d = start_date
    for p in prices:
        while d.weekday() >= 5:
            d += dt.timedelta(days=1)
        bars.append(
            MarketPriceBar(
                symbol=symbol,
                price_date=d,
                open=round(p, 4),
                high=round(p * 1.005, 4),
                low=round(p * 0.995, 4),
                close=round(p, 4),
                adjusted_close=round(p, 4),
                volume=500_000,
                provider="test",
            )
        )
        d += dt.timedelta(days=1)
    return bars


# ── compute_forward_outcome ───────────────────────────────────────────────────


def test_buy_candidate_win_positive_return() -> None:
    start = dt.date(2024, 1, 2)
    bars = _make_bars("AAPL", start, 30, 100.0, daily_return=0.004)  # ~+12% over 30 bars
    bench = _make_bars("SPY", start, 30, 400.0, daily_return=0.0005)  # +1.5%

    result = compute_forward_outcome("BUY_CANDIDATE", bars, bench, horizon_days=30)

    assert result.outcome_status == "MEASURED"
    assert result.forward_return_pct is not None and result.forward_return_pct > 0.03
    assert result.benchmark_return_pct is not None and result.benchmark_return_pct > 0
    assert result.relative_return_pct is not None and result.relative_return_pct > 0.05
    assert result.outcome_label == "WIN"


def test_buy_candidate_loss_negative_return() -> None:
    start = dt.date(2024, 1, 2)
    bars = _make_bars("TSLA", start, 30, 200.0, daily_return=-0.004)  # ~-11%
    bench = _make_bars("SPY", start, 30, 400.0, daily_return=0.001)

    result = compute_forward_outcome("BUY_CANDIDATE", bars, bench, horizon_days=30)

    assert result.outcome_status == "MEASURED"
    assert result.forward_return_pct is not None and result.forward_return_pct < -0.03
    assert result.outcome_label == "LOSS"


def test_hold_missed_upside() -> None:
    start = dt.date(2024, 1, 2)
    bars = _make_bars("NVDA", start, 30, 500.0, daily_return=0.008)  # +27%

    result = compute_forward_outcome("HOLD", bars, None, horizon_days=30)

    assert result.outcome_status == "MEASURED"
    assert result.forward_return_pct is not None and result.forward_return_pct > 0.10
    assert result.outcome_label == "MISSED_UPSIDE"


def test_reduce_avoided_loss() -> None:
    start = dt.date(2024, 1, 2)
    bars = _make_bars("AMD", start, 30, 150.0, daily_return=-0.003)  # ~-8%

    result = compute_forward_outcome("REDUCE", bars, None, horizon_days=30)

    assert result.outcome_status == "MEASURED"
    assert result.forward_return_pct is not None and result.forward_return_pct < -0.05
    assert result.outcome_label == "AVOIDED_LOSS"


def test_insufficient_bars_returns_insufficient_data() -> None:
    start = dt.date(2024, 1, 2)
    # Only 2 bars for a 30-day horizon
    bars = _make_bars("AAPL", start, 2, 100.0)

    result = compute_forward_outcome("BUY_CANDIDATE", bars, None, horizon_days=30)

    assert result.outcome_status == "INSUFFICIENT_DATA"
    assert result.outcome_label is None


def test_no_bars_returns_insufficient_data() -> None:
    result = compute_forward_outcome("HOLD", [], None, horizon_days=30)
    assert result.outcome_status == "INSUFFICIENT_DATA"


def test_max_drawdown_and_runup_computed() -> None:
    start = dt.date(2024, 1, 2)
    bars = _make_drawdown_bars("AAPL", start, 100.0)

    result = compute_forward_outcome("BUY_CANDIDATE", bars, None, horizon_days=20)

    assert result.outcome_status == "MEASURED"
    assert result.max_drawdown_pct is not None and result.max_drawdown_pct < -0.08
    assert result.max_runup_pct is not None  # may be 0 if no gain above start


def test_strong_buy_classified_same_as_buy_candidate() -> None:
    start = dt.date(2024, 1, 2)
    bars = _make_bars("MSFT", start, 30, 300.0, daily_return=0.004)
    result = compute_forward_outcome("STRONG_BUY", bars, None, horizon_days=30)
    assert result.outcome_label in {"WIN", "NEUTRAL", "LOSS"}  # not UNKNOWN


def test_max_runup_positive_when_price_rises() -> None:
    start = dt.date(2024, 1, 2)
    bars = _make_bars("SPY", start, 30, 400.0, daily_return=0.005)
    result = compute_forward_outcome("HOLD", bars, None, horizon_days=30)
    assert result.max_runup_pct is not None and result.max_runup_pct > 0


def test_classify_label_buy_neutral() -> None:
    label = _classify_label("BUY_CANDIDATE", 0.01, 0.02, -0.02)
    assert label == "NEUTRAL"  # +1% but underperforms bench by -1%


# ── should_generate_learning_event + build_learning_event_fields ──────────────


def test_buy_loss_triggers_learning_event() -> None:
    outcome = ForwardOutcome(
        forward_return_pct=-0.10,
        relative_return_pct=-0.12,
        max_drawdown_pct=-0.10,
        outcome_status="MEASURED",
        outcome_label="LOSS",
    )
    assert should_generate_learning_event(outcome, "BUY_CANDIDATE") is True


def test_hold_missed_upside_triggers() -> None:
    outcome = ForwardOutcome(
        forward_return_pct=0.15,
        outcome_status="MEASURED",
        outcome_label="MISSED_UPSIDE",
    )
    assert should_generate_learning_event(outcome, "HOLD") is True


def test_mild_neutral_outcome_no_event() -> None:
    outcome = ForwardOutcome(
        forward_return_pct=0.01,
        outcome_status="MEASURED",
        outcome_label="NEUTRAL",
    )
    assert should_generate_learning_event(outcome, "BUY_CANDIDATE") is False


def test_insufficient_data_no_event() -> None:
    outcome = ForwardOutcome(outcome_status="INSUFFICIENT_DATA")
    assert should_generate_learning_event(outcome, "BUY_CANDIDATE") is False


def test_buy_loss_fields_event_type() -> None:
    outcome = ForwardOutcome(
        forward_return_pct=-0.09,
        relative_return_pct=-0.11,
        max_drawdown_pct=-0.09,
        outcome_status="MEASURED",
        outcome_label="LOSS",
    )
    fields = build_learning_event_fields(outcome, "BUY_CANDIDATE", "AAPL")
    assert fields["event_type"] == "UNDERPERFORMED_AFTER_BUY"
    assert fields["severity"] in {"MEDIUM", "HIGH"}
    assert "AAPL" in fields["title"]


def test_hold_missed_upside_fields() -> None:
    outcome = ForwardOutcome(
        forward_return_pct=0.20,
        outcome_status="MEASURED",
        outcome_label="MISSED_UPSIDE",
    )
    fields = build_learning_event_fields(outcome, "HOLD", "NVDA")
    assert fields["event_type"] == "MISSED_UPSIDE_AFTER_HOLD"
    assert "NVDA" in fields["title"]


def test_stop_loss_drawdown_triggers() -> None:
    outcome = ForwardOutcome(
        forward_return_pct=0.01,
        max_drawdown_pct=-0.12,
        outcome_status="MEASURED",
        outcome_label="NEUTRAL",
    )
    assert should_generate_learning_event(outcome, "BUY_CANDIDATE") is True
    fields = build_learning_event_fields(outcome, "BUY_CANDIDATE", "TSLA")
    assert fields["event_type"] == "STOP_LOSS_LIKE_DRAWDOWN"


def test_build_learning_event_summary_includes_all_parts() -> None:
    """Summary for BUY loss includes forward return, benchmark-relative, and drawdown."""
    outcome = ForwardOutcome(
        forward_return_pct=-0.09,
        relative_return_pct=-0.11,
        max_drawdown_pct=-0.10,
        outcome_status="MEASURED",
        outcome_label="LOSS",
    )
    fields = build_learning_event_fields(outcome, "BUY_CANDIDATE", "AAPL")
    summary = fields["summary"]
    assert "-9.0%" in summary or "-9" in summary  # forward return present
    assert "-11.0%" in summary or "-11" in summary  # relative present
    assert "-10.0%" in summary or "-10" in summary  # drawdown present


def test_build_learning_event_summary_no_benchmark_or_drawdown() -> None:
    """Summary is not broken when benchmark and drawdown are absent."""
    outcome = ForwardOutcome(
        forward_return_pct=-0.05,
        relative_return_pct=None,
        max_drawdown_pct=None,
        outcome_status="MEASURED",
        outcome_label="LOSS",
    )
    fields = build_learning_event_fields(outcome, "BUY_CANDIDATE", "AAPL")
    assert fields["summary"]  # non-empty
    assert "None" not in fields["summary"]


# ── DB-bound tests ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_measure_recommendation_outcome_persists(db_session):
    """Outcome row is persisted correctly for a BUY with 30 bars."""
    from db.enums import ResearchRunStatus, ResearchRunType
    from db.models import MarketPrice, NeutralRecommendation
    from db.repositories import ResearchRunRepository

    # Seed run + neutral rec
    rr_repo = ResearchRunRepository(db_session)
    run = await rr_repo.create(run_type=ResearchRunType.MANUAL)
    await rr_repo.update_status(run.id, ResearchRunStatus.COMPLETED)
    await rr_repo.add_tickers(run.id, ["AAPL"])

    as_of = dt.datetime(2024, 1, 2, 12, 0, tzinfo=dt.UTC)
    nr = NeutralRecommendation(
        research_run_id=run.id,
        symbol="AAPL",
        action="BUY_CANDIDATE",
        score=72,
        confidence=0.75,
        final_reason="Test",
        score_breakdown_json={},
        main_reasons_json=[],
        main_risks_json=[],
        missing_details_json=[],
        what_changed_json=[],
        as_of_time=as_of,
        price_at_recommendation=100.0,
    )
    db_session.add(nr)
    await db_session.flush()

    # Seed market prices (30 trading bars after rec date)
    start = dt.date(2024, 1, 2)
    bars = _make_bars("AAPL", start, 30, 100.0, daily_return=0.004)
    mp_rows = [
        MarketPrice(
            symbol=b.symbol,
            price_date=b.price_date,
            open=b.open,
            high=b.high,
            low=b.low,
            close=b.close,
            adjusted_close=b.adjusted_close,
            volume=b.volume,
            provider="yfinance",
        )
        for b in bars
    ]
    db_session.add_all(mp_rows)
    await db_session.flush()

    outcome = await measure_recommendation_outcome(
        session=db_session,
        recommendation_type="NEUTRAL",
        recommendation_id=nr.id,
        symbol="AAPL",
        action="BUY_CANDIDATE",
        score=72,
        price_at_recommendation=100.0,
        measured_from=as_of,
        horizon_days=30,
        benchmark_symbol="SPY",
        research_run_id=run.id,
        user_id=None,
    )

    assert outcome.outcome_status == "MEASURED"
    assert outcome.forward_return_pct is not None and float(outcome.forward_return_pct) > 0
    assert outcome.symbol == "AAPL"


@pytest.mark.asyncio
async def test_measure_outcome_idempotent(db_session):
    """Calling measure twice returns the same row without creating a duplicate."""
    from db.enums import ResearchRunStatus, ResearchRunType
    from db.models import MarketPrice, NeutralRecommendation
    from db.repositories import ResearchRunRepository

    rr_repo = ResearchRunRepository(db_session)
    run = await rr_repo.create(run_type=ResearchRunType.MANUAL)
    await rr_repo.update_status(run.id, ResearchRunStatus.COMPLETED)
    await rr_repo.add_tickers(run.id, ["MSFT"])

    as_of = dt.datetime(2024, 2, 1, 10, 0, tzinfo=dt.UTC)
    nr = NeutralRecommendation(
        research_run_id=run.id,
        symbol="MSFT",
        action="HOLD",
        score=60,
        confidence=0.70,
        final_reason="Test",
        score_breakdown_json={},
        main_reasons_json=[],
        main_risks_json=[],
        missing_details_json=[],
        what_changed_json=[],
        as_of_time=as_of,
    )
    db_session.add(nr)
    await db_session.flush()

    start = dt.date(2024, 2, 1)
    bars = _make_bars("MSFT", start, 30, 300.0, daily_return=0.002)
    db_session.add_all(
        [
            MarketPrice(
                symbol=b.symbol,
                price_date=b.price_date,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                adjusted_close=b.adjusted_close,
                volume=1_000_000,
                provider="yfinance",
            )
            for b in bars
        ]
    )
    await db_session.flush()

    kwargs = {
        "session": db_session,
        "recommendation_type": "NEUTRAL",
        "recommendation_id": nr.id,
        "symbol": "MSFT",
        "action": "HOLD",
        "score": 60,
        "price_at_recommendation": None,
        "measured_from": as_of,
        "horizon_days": 30,
        "benchmark_symbol": "SPY",
        "research_run_id": run.id,
        "user_id": None,
    }

    r1 = await measure_recommendation_outcome(**kwargs)
    r2 = await measure_recommendation_outcome(**kwargs)
    assert r1.id == r2.id


@pytest.mark.asyncio
async def test_generate_learning_event_for_buy_loss(db_session):
    """BUY_CANDIDATE with loss outcome creates a learning event."""
    from db.enums import ResearchRunType
    from db.models import MarketPrice, NeutralRecommendation
    from db.repositories import ResearchRunRepository

    rr_repo = ResearchRunRepository(db_session)
    run = await rr_repo.create(run_type=ResearchRunType.MANUAL)
    await rr_repo.add_tickers(run.id, ["TSLA"])
    as_of = dt.datetime(2024, 3, 1, 10, 0, tzinfo=dt.UTC)
    nr = NeutralRecommendation(
        research_run_id=run.id,
        symbol="TSLA",
        action="BUY_CANDIDATE",
        score=75,
        confidence=0.70,
        final_reason="Test",
        score_breakdown_json={},
        main_reasons_json=[],
        main_risks_json=[],
        missing_details_json=[],
        what_changed_json=[],
        as_of_time=as_of,
    )
    db_session.add(nr)
    await db_session.flush()

    # Seed losing bars
    start = dt.date(2024, 3, 1)
    bars = _make_bars("TSLA", start, 30, 200.0, daily_return=-0.005)
    db_session.add_all(
        [
            MarketPrice(
                symbol=b.symbol,
                price_date=b.price_date,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                adjusted_close=b.adjusted_close,
                volume=500_000,
                provider="yfinance",
            )
            for b in bars
        ]
    )
    await db_session.flush()

    outcome_row = await measure_recommendation_outcome(
        session=db_session,
        recommendation_type="NEUTRAL",
        recommendation_id=nr.id,
        symbol="TSLA",
        action="BUY_CANDIDATE",
        score=75,
        price_at_recommendation=200.0,
        measured_from=as_of,
        horizon_days=30,
        benchmark_symbol="SPY",
        research_run_id=run.id,
        user_id=None,
    )
    assert outcome_row.outcome_label == "LOSS"

    event = await generate_learning_event_from_outcome(
        session=db_session,
        outcome_row=outcome_row,
        action="BUY_CANDIDATE",
        symbol="TSLA",
        user_id=None,
        research_run_id=run.id,
    )
    assert event is not None
    assert event.event_type == "UNDERPERFORMED_AFTER_BUY"
    assert event.status == "OPEN"


@pytest.mark.asyncio
async def test_no_learning_event_for_neutral_outcome(db_session):
    """Mild NEUTRAL outcome does not create a noisy learning event."""
    from db.enums import ResearchRunType
    from db.models import MarketPrice, NeutralRecommendation
    from db.repositories import ResearchRunRepository

    rr_repo = ResearchRunRepository(db_session)
    run = await rr_repo.create(run_type=ResearchRunType.MANUAL)
    await rr_repo.add_tickers(run.id, ["SPY"])
    as_of = dt.datetime(2024, 4, 1, 10, 0, tzinfo=dt.UTC)
    nr = NeutralRecommendation(
        research_run_id=run.id,
        symbol="SPY",
        action="HOLD",
        score=55,
        confidence=0.70,
        final_reason="Test",
        score_breakdown_json={},
        main_reasons_json=[],
        main_risks_json=[],
        missing_details_json=[],
        what_changed_json=[],
        as_of_time=as_of,
    )
    db_session.add(nr)
    await db_session.flush()

    start = dt.date(2024, 4, 1)
    bars = _make_bars("SPY", start, 30, 400.0, daily_return=0.001)  # mild +3%
    db_session.add_all(
        [
            MarketPrice(
                symbol=b.symbol,
                price_date=b.price_date,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                adjusted_close=b.adjusted_close,
                volume=5_000_000,
                provider="yfinance",
            )
            for b in bars
        ]
    )
    await db_session.flush()

    outcome_row = await measure_recommendation_outcome(
        session=db_session,
        recommendation_type="NEUTRAL",
        recommendation_id=nr.id,
        symbol="SPY",
        action="HOLD",
        score=55,
        price_at_recommendation=400.0,
        measured_from=as_of,
        horizon_days=30,
        benchmark_symbol="SPY",
        research_run_id=run.id,
        user_id=None,
    )

    event = await generate_learning_event_from_outcome(
        session=db_session,
        outcome_row=outcome_row,
        action="HOLD",
        symbol="SPY",
        user_id=None,
    )
    assert event is None


# ── Horizon guard tests ───────────────────────────────────────────────────────


def _make_rec(db_session, run_id, symbol: str, as_of: dt.datetime):
    """Helper: seed a NeutralRecommendation and return it."""
    from db.models import NeutralRecommendation

    nr = NeutralRecommendation(
        research_run_id=run_id,
        symbol=symbol,
        action="BUY_CANDIDATE",
        score=72,
        confidence=0.75,
        final_reason="Horizon test",
        score_breakdown_json={},
        main_reasons_json=[],
        main_risks_json=[],
        missing_details_json=[],
        what_changed_json=[],
        as_of_time=as_of,
        price_at_recommendation=100.0,
    )
    db_session.add(nr)
    return nr


async def _seed_run(db_session):
    from db.enums import ResearchRunType
    from db.repositories import ResearchRunRepository

    rr_repo = ResearchRunRepository(db_session)
    run = await rr_repo.create(run_type=ResearchRunType.MANUAL)
    await rr_repo.add_tickers(run.id, ["AAPL"])
    return run


@pytest.mark.asyncio
async def test_horizon_not_elapsed_returns_pending(db_session):
    """Calling before horizon end persists PENDING, never INSUFFICIENT_DATA."""
    run = await _seed_run(db_session)
    # Recommendation made "now"; horizon=30 days into the future
    now = dt.datetime(2025, 6, 1, 12, 0, tzinfo=dt.UTC)
    as_of = now - dt.timedelta(days=1)  # 1 day old, horizon 30 days → not elapsed
    nr = _make_rec(db_session, run.id, "AAPL", as_of)
    await db_session.flush()

    outcome = await measure_recommendation_outcome(
        session=db_session,
        recommendation_type="NEUTRAL",
        recommendation_id=nr.id,
        symbol="AAPL",
        action="BUY_CANDIDATE",
        score=72,
        price_at_recommendation=100.0,
        measured_from=as_of,
        horizon_days=30,
        benchmark_symbol="SPY",
        research_run_id=run.id,
        user_id=None,
        _now=now,
    )

    assert outcome.outcome_status == "PENDING"
    assert outcome.outcome_label is None


@pytest.mark.asyncio
async def test_pending_not_updated_before_horizon_elapses(db_session):
    """Calling twice before horizon end returns the same PENDING row unchanged."""
    run = await _seed_run(db_session)
    now = dt.datetime(2025, 7, 1, 12, 0, tzinfo=dt.UTC)
    as_of = now - dt.timedelta(days=5)
    nr = _make_rec(db_session, run.id, "AAPL", as_of)
    await db_session.flush()

    kwargs = {
        "session": db_session,
        "recommendation_type": "NEUTRAL",
        "recommendation_id": nr.id,
        "symbol": "AAPL",
        "action": "BUY_CANDIDATE",
        "score": 72,
        "price_at_recommendation": 100.0,
        "measured_from": as_of,
        "horizon_days": 30,
        "benchmark_symbol": "SPY",
        "research_run_id": run.id,
        "user_id": None,
        "_now": now,
    }
    r1 = await measure_recommendation_outcome(**kwargs)
    r2 = await measure_recommendation_outcome(**kwargs)

    assert r1.id == r2.id
    assert r2.outcome_status == "PENDING"


@pytest.mark.asyncio
async def test_pending_becomes_measured_after_horizon_elapses(db_session):
    """PENDING row is updated to MEASURED once horizon has elapsed and bars exist."""
    from db.models import MarketPrice

    run = await _seed_run(db_session)
    as_of = dt.datetime(2024, 5, 1, 12, 0, tzinfo=dt.UTC)
    nr = _make_rec(db_session, run.id, "AAPL", as_of)
    await db_session.flush()

    now_before = as_of + dt.timedelta(days=5)  # horizon not elapsed

    r1 = await measure_recommendation_outcome(
        session=db_session,
        recommendation_type="NEUTRAL",
        recommendation_id=nr.id,
        symbol="AAPL",
        action="BUY_CANDIDATE",
        score=72,
        price_at_recommendation=100.0,
        measured_from=as_of,
        horizon_days=30,
        benchmark_symbol="SPY",
        research_run_id=run.id,
        user_id=None,
        _now=now_before,
    )
    assert r1.outcome_status == "PENDING"

    # Seed bars so re-measurement can produce MEASURED
    start_date = as_of.date()
    bars = _make_bars("AAPL", start_date, 40, 100.0, daily_return=0.003)
    db_session.add_all(
        [
            MarketPrice(
                symbol=b.symbol,
                price_date=b.price_date,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                adjusted_close=b.adjusted_close,
                volume=1_000_000,
                provider="yfinance",
            )
            for b in bars
        ]
    )
    await db_session.flush()

    now_after = as_of + dt.timedelta(days=35)  # horizon elapsed

    r2 = await measure_recommendation_outcome(
        session=db_session,
        recommendation_type="NEUTRAL",
        recommendation_id=nr.id,
        symbol="AAPL",
        action="BUY_CANDIDATE",
        score=72,
        price_at_recommendation=100.0,
        measured_from=as_of,
        horizon_days=30,
        benchmark_symbol="SPY",
        research_run_id=run.id,
        user_id=None,
        _now=now_after,
    )

    assert r2.id == r1.id  # same row, updated in place
    assert r2.outcome_status == "MEASURED"
    assert r2.forward_return_pct is not None


@pytest.mark.asyncio
async def test_insufficient_data_remeasured_when_bars_appear(db_session):
    """INSUFFICIENT_DATA row can be upgraded to MEASURED once bars exist."""
    from db.models import MarketPrice

    run = await _seed_run(db_session)
    as_of = dt.datetime(2024, 8, 1, 12, 0, tzinfo=dt.UTC)
    nr = _make_rec(db_session, run.id, "AAPL", as_of)
    await db_session.flush()

    # First call: horizon elapsed but no bars → INSUFFICIENT_DATA
    now_elapsed = as_of + dt.timedelta(days=40)

    r1 = await measure_recommendation_outcome(
        session=db_session,
        recommendation_type="NEUTRAL",
        recommendation_id=nr.id,
        symbol="AAPL",
        action="BUY_CANDIDATE",
        score=72,
        price_at_recommendation=100.0,
        measured_from=as_of,
        horizon_days=30,
        benchmark_symbol="SPY",
        research_run_id=run.id,
        user_id=None,
        _now=now_elapsed,
    )
    assert r1.outcome_status == "INSUFFICIENT_DATA"

    # Now seed bars
    start_date = as_of.date()
    bars = _make_bars("AAPL", start_date, 40, 100.0, daily_return=0.004)
    db_session.add_all(
        [
            MarketPrice(
                symbol=b.symbol,
                price_date=b.price_date,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                adjusted_close=b.adjusted_close,
                volume=1_000_000,
                provider="yfinance",
            )
            for b in bars
        ]
    )
    await db_session.flush()

    # Second call with same _now: should re-measure and produce MEASURED
    r2 = await measure_recommendation_outcome(
        session=db_session,
        recommendation_type="NEUTRAL",
        recommendation_id=nr.id,
        symbol="AAPL",
        action="BUY_CANDIDATE",
        score=72,
        price_at_recommendation=100.0,
        measured_from=as_of,
        horizon_days=30,
        benchmark_symbol="SPY",
        research_run_id=run.id,
        user_id=None,
        _now=now_elapsed,
    )
    assert r2.id == r1.id
    assert r2.outcome_status == "MEASURED"


@pytest.mark.asyncio
async def test_measured_row_is_never_overwritten(db_session):
    """A MEASURED outcome is returned idempotently and never re-computed."""
    from db.models import MarketPrice

    run = await _seed_run(db_session)
    as_of = dt.datetime(2024, 9, 1, 12, 0, tzinfo=dt.UTC)
    nr = _make_rec(db_session, run.id, "AAPL", as_of)
    await db_session.flush()

    start_date = as_of.date()
    bars = _make_bars("AAPL", start_date, 40, 100.0, daily_return=0.005)
    db_session.add_all(
        [
            MarketPrice(
                symbol=b.symbol,
                price_date=b.price_date,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                adjusted_close=b.adjusted_close,
                volume=1_000_000,
                provider="yfinance",
            )
            for b in bars
        ]
    )
    await db_session.flush()

    now = as_of + dt.timedelta(days=40)

    r1 = await measure_recommendation_outcome(
        session=db_session,
        recommendation_type="NEUTRAL",
        recommendation_id=nr.id,
        symbol="AAPL",
        action="BUY_CANDIDATE",
        score=72,
        price_at_recommendation=100.0,
        measured_from=as_of,
        horizon_days=30,
        benchmark_symbol="SPY",
        research_run_id=run.id,
        user_id=None,
        _now=now,
    )
    assert r1.outcome_status == "MEASURED"
    original_return = r1.forward_return_pct

    # Call again — should return the same row without modification
    r2 = await measure_recommendation_outcome(
        session=db_session,
        recommendation_type="NEUTRAL",
        recommendation_id=nr.id,
        symbol="AAPL",
        action="BUY_CANDIDATE",
        score=72,
        price_at_recommendation=100.0,
        measured_from=as_of,
        horizon_days=30,
        benchmark_symbol="SPY",
        research_run_id=run.id,
        user_id=None,
        _now=now,
    )
    assert r2.id == r1.id
    assert r2.outcome_status == "MEASURED"
    assert r2.forward_return_pct == original_return
