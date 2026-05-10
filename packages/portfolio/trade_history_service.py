"""Trade history service — sync IBKR → DB, merge with manual trades, build profile."""

from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING, Any

from broker.ibkr.schemas import IBKRExecution as IBKRExecutionSchema
from db.repositories import (
    IBKRExecutionRepository,
    ManualTradeRepository,
    TradingProfileSnapshotRepository,
)

from portfolio.trading_profile import build_trading_profile

if TYPE_CHECKING:
    from collections.abc import Sequence

    from db.models import ManualTrade as _ManualTrade
    from db.models import TradingProfileSnapshot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def sync_ibkr_executions(
    session: AsyncSession,
    executions: Sequence[IBKRExecutionSchema],
) -> int:
    """Persist IBKR executions; skip duplicates by exec_id. Returns count inserted."""
    repo = IBKRExecutionRepository(session)
    inserted = 0
    for ex in executions:
        if await repo.exists_by_exec_id(ex.exec_id):
            continue
        await repo.create(ex)
        inserted += 1
    logger.info("ibkr_executions_synced", extra={"inserted": inserted, "total": len(executions)})
    return inserted


async def load_all_executions(
    session: AsyncSession,
    months: int = 12,
    symbol: str | None = None,
) -> list[IBKRExecutionSchema]:
    """Load IBKR + manual executions from DB, merged and sorted by time."""
    ibkr_repo = IBKRExecutionRepository(session)
    manual_repo = ManualTradeRepository(session)

    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=months * 31)

    ibkr_rows = await ibkr_repo.list_since(since, symbol=symbol)
    manual_rows = await manual_repo.list_since(since, symbol=symbol)

    combined: list[IBKRExecutionSchema] = []

    for row in ibkr_rows:
        combined.append(
            IBKRExecutionSchema(
                exec_id=row.exec_id,
                account_id_ibkr=row.account_id_ibkr,
                symbol=row.symbol,
                exchange=row.exchange,
                side=row.side,  # type: ignore[arg-type]
                quantity=float(row.quantity),
                price=float(row.price),
                commission=float(row.commission) if row.commission is not None else None,
                currency=row.currency,
                executed_at=row.executed_at,
                order_ref=row.order_ref,
                raw_json=row.raw_json or {},
            )
        )

    # Manual trades injected as synthetic executions
    for manual_row in manual_rows:
        mt: _ManualTrade = manual_row
        combined.append(
            IBKRExecutionSchema(
                exec_id=f"manual-{mt.id}",
                account_id_ibkr="MANUAL",
                symbol=mt.symbol,
                side=mt.side,  # type: ignore[arg-type]
                quantity=float(mt.quantity),
                price=float(mt.price),
                currency="USD",
                executed_at=mt.executed_at,
                raw_json={"source": mt.source, "notes": mt.notes},
            )
        )

    combined.sort(key=lambda e: e.executed_at)
    return combined


async def build_and_save_profile(
    session: AsyncSession,
    period_months: int = 12,
    market_prices: dict[str, float] | None = None,
) -> TradingProfileSnapshot:
    """Compute trading profile and persist a snapshot."""
    executions = await load_all_executions(session, months=period_months)
    profile = build_trading_profile(
        executions,
        period_months=period_months,
        market_prices=market_prices,
    )

    repo = TradingProfileSnapshotRepository(session)
    snapshot = await repo.create(profile)
    logger.info(
        "trading_profile_snapshot_saved",
        extra={
            "as_of_date": str(profile.as_of_date),
            "total_executions": profile.total_executions,
            "win_rate": profile.win_rate,
        },
    )
    return snapshot


async def get_symbol_trading_stats(
    session: AsyncSession,
    symbol: str,
    months: int = 12,
) -> dict[str, Any]:
    """Return per-symbol trading stats for use in the research graph."""
    executions = await load_all_executions(session, months=months, symbol=symbol)
    if not executions:
        return {}

    profile = build_trading_profile(executions, period_months=months)
    return profile.per_symbol_stats.get(symbol, {})  # type: ignore[return-value]


async def get_latest_profile(
    session: AsyncSession,
) -> TradingProfileSnapshot | None:
    repo = TradingProfileSnapshotRepository(session)
    return await repo.latest()
