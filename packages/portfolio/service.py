"""Portfolio service — ensure default account, refresh prices, build snapshots."""

import uuid
from datetime import UTC, datetime

from core.logging import get_logger
from db.models import PortfolioAccount, PortfolioSnapshot
from db.repositories import (
    InvestorProfileRepository,
    PortfolioAccountRepository,
    PortfolioPositionRepository,
    PortfolioSnapshotRepository,
)
from market_data.repository import MarketPriceRepository
from sqlalchemy.ext.asyncio import AsyncSession

from portfolio.risk import concentration_score
from portfolio.schemas import PortfolioContext, PortfolioPositionContext

logger = get_logger(__name__)


async def ensure_default_portfolio(
    session: AsyncSession,
    user_id: uuid.UUID | None = None,
) -> PortfolioAccount:
    acc_repo = PortfolioAccountRepository(session)
    return await acc_repo.get_or_create_default(user_id=user_id)


async def refresh_portfolio_prices(
    session: AsyncSession,
    account_id: uuid.UUID | None = None,
) -> None:
    """Update current_price on each position from stored market_prices."""
    acc_repo = PortfolioAccountRepository(session)
    if account_id is None:
        account = await acc_repo.get_default()
        if account is None:
            return
        account_id = account.id

    pos_repo = PortfolioPositionRepository(session)
    price_repo = MarketPriceRepository(session)
    positions = await pos_repo.list_by_account(account_id)

    for pos in positions:
        price = await price_repo.get_latest_close(pos.symbol)
        if price is not None:
            pos.current_price = price
            qty = float(pos.quantity)
            pos.market_value = qty * price
            if pos.average_cost is not None:
                pos.cost_basis = qty * float(pos.average_cost)
                if pos.cost_basis and float(pos.cost_basis) != 0:
                    pos.unrealized_pnl = float(pos.market_value) - float(pos.cost_basis)
                    pos.unrealized_pnl_pct = float(pos.unrealized_pnl) / float(pos.cost_basis)
            pos.as_of_time = datetime.now(UTC)

    await session.flush()
    logger.info("portfolio_prices_refreshed", account_id=str(account_id), positions=len(positions))


async def build_portfolio_snapshot(
    session: AsyncSession,
    account_id: uuid.UUID,
) -> PortfolioSnapshot:
    """Recompute weights and save a new snapshot row."""
    pos_repo = PortfolioPositionRepository(session)
    snap_repo = PortfolioSnapshotRepository(session)

    account = await session.get(PortfolioAccount, account_id)
    cash = float(account.cash_balance) if account else 0.0

    positions = await pos_repo.list_by_account(account_id)
    total_market_value = sum(float(p.market_value or 0) for p in positions)
    total_equity = total_market_value + cash

    if total_equity > 0:
        await pos_repo.update_weights(account_id, total_equity)
        positions = await pos_repo.list_by_account(account_id)

    snap = await snap_repo.create_snapshot(account_id, positions, cash)
    logger.info(
        "portfolio_snapshot_created",
        account_id=str(account_id),
        total_equity=total_equity,
        positions=len(positions),
    )
    return snap


async def get_portfolio_context_for_symbol(
    session: AsyncSession,
    symbol: str,
    user_id: uuid.UUID | None = None,
) -> PortfolioContext | None:
    """
    Load portfolio context for a specific symbol.
    Returns None if no default portfolio exists.
    """
    acc_repo = PortfolioAccountRepository(session)
    account = await acc_repo.get_default(user_id=user_id)
    if account is None:
        return None

    pos_repo = PortfolioPositionRepository(session)
    snap_repo = PortfolioSnapshotRepository(session)
    ip_repo = InvestorProfileRepository(session)

    positions = await pos_repo.list_by_account(account.id)
    latest_snap = await snap_repo.latest(account.id)

    profile = await ip_repo.get_default(user_id=user_id)
    risk_level = profile.risk_level if profile else "MEDIUM"
    min_confidence = profile.min_confidence_to_buy if profile else 0.65
    max_weight = profile.max_single_stock_weight if profile else 0.15

    cash = float(account.cash_balance)
    total_market_value = sum(float(p.market_value or 0) for p in positions)
    total_equity = total_market_value + cash
    cash_pct = cash / total_equity if total_equity > 0 else 1.0

    max_pos_weight = latest_snap.max_position_weight if latest_snap else None
    conc = concentration_score(max_pos_weight or 0.0)
    largest_sym: str | None = None
    if latest_snap and latest_snap.risk_metrics_json:
        largest_sym = latest_snap.risk_metrics_json.get("largest_position_symbol")

    # Compute market values on-the-fly from latest market_prices if position values are stale.
    # This handles positions added before prices existed, or after a research run loaded new prices.
    price_repo = MarketPriceRepository(session)
    live_market_values: dict[str, float] = {}
    for p in positions:
        mv = float(p.market_value) if p.market_value is not None else None
        if mv is None:
            price = await price_repo.get_latest_close(p.symbol)
            if price is not None:
                mv = float(p.quantity) * price
        if mv is not None:
            live_market_values[p.symbol] = mv

    live_total_market_value = sum(live_market_values.values())
    live_total_equity = live_total_market_value + cash
    if live_total_equity > 0 and abs(live_total_equity - total_equity) > 0.01:
        # Recompute with live values
        total_market_value = live_total_market_value
        total_equity = live_total_equity
        cash_pct = cash / total_equity

    position_ctx: PortfolioPositionContext | None = None
    pos = next((p for p in positions if p.symbol == symbol.upper()), None)
    if pos is not None:
        # Prefer stored weight; fall back to on-the-fly computation if None
        if pos.weight is not None:
            pos_weight = float(pos.weight)
        elif symbol.upper() in live_market_values and total_equity > 0:
            pos_weight = live_market_values[symbol.upper()] / total_equity
        else:
            pos_weight = 0.0
        mv_for_pos = live_market_values.get(symbol.upper()) or (
            float(pos.market_value) if pos.market_value else None
        )
        position_ctx = PortfolioPositionContext(
            symbol=pos.symbol,
            quantity=float(pos.quantity),
            average_cost=float(pos.average_cost) if pos.average_cost else None,
            current_price=float(pos.current_price) if pos.current_price else None,
            market_value=mv_for_pos,
            cost_basis=float(pos.cost_basis) if pos.cost_basis else None,
            unrealized_pnl=float(pos.unrealized_pnl) if pos.unrealized_pnl else None,
            unrealized_pnl_pct=(float(pos.unrealized_pnl_pct) if pos.unrealized_pnl_pct else None),
            weight=pos_weight,
        )

    return PortfolioContext(
        account_id=account.id,
        snapshot_id=latest_snap.id if latest_snap else None,
        total_equity=total_equity,
        total_market_value=total_market_value,
        cash_balance=cash,
        cash_pct=round(cash_pct, 4),
        number_of_positions=len(positions),
        max_position_weight=max_pos_weight or 0.0,
        largest_position_symbol=largest_sym,
        concentration_score=conc,
        risk_level=risk_level,
        min_confidence_to_buy=min_confidence,
        max_single_stock_weight=max_weight,
        position=position_ctx,
    )
