"""Tests for portfolio service and risk module — require DB."""

import pytest
from portfolio.risk import (
    classify_position_size,
    concentration_score,
    portfolio_fit_score,
    recommended_position_size,
)
from portfolio.service import (
    build_portfolio_snapshot,
    ensure_default_portfolio,
    get_portfolio_context_for_symbol,
)


@pytest.mark.asyncio
async def test_creates_default_portfolio(db_session) -> None:
    account = await ensure_default_portfolio(db_session)
    assert account is not None
    assert account.is_active is True
    assert account.account_type == "MANUAL"


@pytest.mark.asyncio
async def test_ensure_default_portfolio_idempotent(db_session) -> None:
    a1 = await ensure_default_portfolio(db_session)
    a2 = await ensure_default_portfolio(db_session)
    assert a1.id == a2.id


@pytest.mark.asyncio
async def test_upserts_positions(db_session) -> None:
    from db.repositories import PortfolioPositionRepository

    account = await ensure_default_portfolio(db_session)
    repo = PortfolioPositionRepository(db_session)

    pos = await repo.upsert_position(
        account_id=account.id,
        symbol="AAPL",
        quantity=10.0,
        average_cost=190.0,
        current_price=200.0,
    )
    assert pos.symbol == "AAPL"
    assert float(pos.quantity) == 10.0
    assert float(pos.market_value) == pytest.approx(2000.0)

    # Update (upsert again)
    pos2 = await repo.upsert_position(
        account_id=account.id,
        symbol="AAPL",
        quantity=15.0,
        average_cost=190.0,
        current_price=200.0,
    )
    assert float(pos2.quantity) == 15.0
    assert float(pos2.market_value) == pytest.approx(3000.0)


@pytest.mark.asyncio
async def test_handles_missing_prices_gracefully(db_session) -> None:
    from db.repositories import PortfolioPositionRepository

    account = await ensure_default_portfolio(db_session)
    repo = PortfolioPositionRepository(db_session)
    pos = await repo.upsert_position(
        account_id=account.id,
        symbol="ZZZZ",
        quantity=5.0,
        average_cost=100.0,
        current_price=None,
    )
    assert pos.market_value is None
    # Snapshot still builds
    snap = await build_portfolio_snapshot(db_session, account.id)
    assert snap is not None


@pytest.mark.asyncio
async def test_builds_snapshot(db_session) -> None:
    from db.repositories import PortfolioPositionRepository

    account = await ensure_default_portfolio(db_session)
    pos_repo = PortfolioPositionRepository(db_session)
    await pos_repo.upsert_position(
        account_id=account.id, symbol="AAPL", quantity=10.0, average_cost=190.0, current_price=200.0
    )
    await pos_repo.upsert_position(
        account_id=account.id, symbol="NVDA", quantity=5.0, average_cost=100.0, current_price=150.0
    )
    snap = await build_portfolio_snapshot(db_session, account.id)
    assert snap.number_of_positions == 2
    assert float(snap.total_market_value) == pytest.approx(2000.0 + 750.0)
    assert snap.max_position_weight is not None
    assert len(snap.top_positions_json) == 2


@pytest.mark.asyncio
async def test_computes_weights(db_session) -> None:
    from db.repositories import PortfolioPositionRepository

    account = await ensure_default_portfolio(db_session)
    pos_repo = PortfolioPositionRepository(db_session)
    await pos_repo.upsert_position(
        account_id=account.id, symbol="AAPL", quantity=10.0, average_cost=100.0, current_price=200.0
    )
    snap = await build_portfolio_snapshot(db_session, account.id)
    cash = float(account.cash_balance)
    total_equity = float(snap.total_market_value) + cash
    assert total_equity > 0
    # Each position weight should sum to ≤1 and be >0
    positions = await pos_repo.list_by_account(account.id)
    for p in positions:
        if p.weight is not None:
            assert 0.0 <= p.weight <= 1.0


@pytest.mark.asyncio
async def test_portfolio_context_no_portfolio(db_session) -> None:
    """Returns None when no portfolio exists."""
    ctx = await get_portfolio_context_for_symbol(db_session, "AAPL")
    # New test DB has no portfolio yet → None
    assert ctx is None


@pytest.mark.asyncio
async def test_portfolio_context_with_portfolio(db_session) -> None:
    from db.repositories import PortfolioPositionRepository

    account = await ensure_default_portfolio(db_session)
    pos_repo = PortfolioPositionRepository(db_session)
    await pos_repo.upsert_position(
        account_id=account.id, symbol="AAPL", quantity=10.0, average_cost=190.0, current_price=200.0
    )
    await build_portfolio_snapshot(db_session, account.id)

    ctx = await get_portfolio_context_for_symbol(db_session, "AAPL")
    assert ctx is not None
    assert ctx.position is not None
    assert ctx.position.symbol == "AAPL"
    assert ctx.position.quantity == pytest.approx(10.0)


# ── Risk module unit tests ────────────────────────────────────────────────────


def test_concentration_score():
    assert concentration_score(0.0) == pytest.approx(0.0)
    assert concentration_score(0.5) == pytest.approx(0.5)
    assert concentration_score(1.5) == pytest.approx(1.0)  # clamped


def test_classify_position_size():
    assert classify_position_size(0.0, 0.15) == "NO_POSITION"
    assert classify_position_size(0.05, 0.15) == "UNDERWEIGHT"
    assert classify_position_size(0.12, 0.15) == "NORMAL"
    assert classify_position_size(0.20, 0.15) == "OVERWEIGHT"


def test_recommended_position_size_gates():
    # Below score gate
    assert recommended_position_size("MEDIUM", 60, 0.80, 0.15) == 0.0
    # Below confidence gate
    assert recommended_position_size("MEDIUM", 75, 0.60, 0.15) == 0.0


def test_recommended_position_size_scaling():
    # HIGH risk, score >= 70, confidence > 0.85 → full cap
    size = recommended_position_size("HIGH", 80, 0.90, 0.15)
    assert size == pytest.approx(0.12, abs=0.01)

    # LOW risk → max 0.05
    size = recommended_position_size("LOW", 80, 0.90, 0.15)
    assert size == pytest.approx(0.05, abs=0.01)

    # MEDIUM, confidence 0.65–0.75 → 50% of max
    size = recommended_position_size("MEDIUM", 80, 0.70, 0.15)
    assert size == pytest.approx(0.04, abs=0.01)  # 0.08 * 0.50


def test_recommended_position_size_respects_max():
    # Even if risk is HIGH, max_single_stock_weight = 0.05 caps it
    size = recommended_position_size("HIGH", 90, 0.90, 0.05)
    assert size == pytest.approx(0.05, abs=0.001)


def test_portfolio_fit_score_no_position_buy():
    """No position + buy signal + low concentration → high fit."""
    score = portfolio_fit_score(
        current_weight=0.0,
        max_weight=0.15,
        cash_balance=10000.0,
        total_equity=50000.0,
        concentration=0.1,
        has_position=False,
        neutral_action="BUY_CANDIDATE",
    )
    assert score > 10.0


def test_portfolio_fit_score_overweight_buy():
    """Already at max weight + buy signal → low fit."""
    score = portfolio_fit_score(
        current_weight=0.15,
        max_weight=0.15,
        cash_balance=1000.0,
        total_equity=50000.0,
        concentration=0.5,
        has_position=True,
        neutral_action="BUY_CANDIDATE",
    )
    assert score < 8.0


def test_portfolio_fit_score_bounded():
    for weight in [0.0, 0.1, 0.5, 1.0]:
        score = portfolio_fit_score(
            current_weight=weight,
            max_weight=0.15,
            cash_balance=5000.0,
            total_equity=50000.0,
            concentration=weight,
            has_position=weight > 0,
            neutral_action="HOLD",
        )
        assert 0.0 <= score <= 15.0
