"""Trade history service — sync IBKR → DB, merge with manual trades, build profile."""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
from typing import TYPE_CHECKING, Any

from broker.ibkr.flex_client import FlexClient
from broker.ibkr.flex_parser import parse_flex_xml
from broker.ibkr.schemas import IBKRExecution as IBKRExecutionSchema
from db.repositories import (
    BrokerAccountRepository,
    IBKRExecutionRepository,
    ManualTradeRepository,
    TradingProfileSnapshotRepository,
)
from sqlalchemy.exc import IntegrityError

from portfolio.trading_profile import build_trading_profile

if TYPE_CHECKING:
    import uuid
    from collections.abc import Sequence

    from db.models import ManualTrade as _ManualTrade
    from db.models import TradingProfileSnapshot
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def sync_ibkr_executions(
    session: AsyncSession,
    executions: Sequence[IBKRExecutionSchema],
    broker_account_id: uuid.UUID | None = None,
) -> int:
    """Persist IBKR executions; skip duplicates by exec_id. Returns count inserted."""
    repo = IBKRExecutionRepository(session)
    ba_repo = BrokerAccountRepository(session)
    inserted = 0
    try:
        for ex in executions:
            if await repo.exists_by_exec_id(ex.exec_id, broker_account_id=broker_account_id):
                continue
            await repo.create(ex, broker_account_id=broker_account_id)
            inserted += 1
        if broker_account_id is not None:
            await ba_repo.mark_sync_success(broker_account_id)
        logger.info(
            "ibkr_executions_synced",
            extra={
                "inserted": inserted,
                "total": len(executions),
                "broker_account_id": str(broker_account_id) if broker_account_id else None,
            },
        )
    except IntegrityError as exc:
        await session.rollback()
        if broker_account_id is not None:
            await ba_repo.mark_sync_failure(broker_account_id, str(exc))
        raise
    except Exception as exc:
        if broker_account_id is not None:
            await ba_repo.mark_sync_failure(broker_account_id, str(exc))
        raise
    return inserted


async def load_all_executions(
    session: AsyncSession,
    months: int = 12,
    symbol: str | None = None,
    broker_account_id: uuid.UUID | None = None,
) -> list[IBKRExecutionSchema]:
    """Load IBKR + manual executions from DB, merged and sorted by time."""
    ibkr_repo = IBKRExecutionRepository(session)
    manual_repo = ManualTradeRepository(session)

    since = dt.datetime.now(dt.UTC) - dt.timedelta(days=months * 31)

    ibkr_rows = await ibkr_repo.list_since(
        since, symbol=symbol, broker_account_id=broker_account_id
    )
    manual_rows = await manual_repo.list_since(
        since, symbol=symbol, broker_account_id=broker_account_id
    )

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
    broker_account_id: uuid.UUID | None = None,
) -> TradingProfileSnapshot:
    """Compute trading profile and persist a snapshot."""
    executions = await load_all_executions(
        session, months=period_months, broker_account_id=broker_account_id
    )
    profile = build_trading_profile(
        executions,
        period_months=period_months,
        market_prices=market_prices,
    )

    repo = TradingProfileSnapshotRepository(session)
    snapshot = await repo.create(profile, broker_account_id=broker_account_id)
    logger.info(
        "trading_profile_snapshot_saved",
        extra={
            "as_of_date": str(profile.as_of_date),
            "total_executions": profile.total_executions,
            "win_rate": profile.win_rate,
            "broker_account_id": str(broker_account_id) if broker_account_id else None,
        },
    )
    return snapshot


async def get_symbol_trading_stats(
    session: AsyncSession,
    symbol: str,
    months: int = 12,
    broker_account_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Return per-symbol trading stats for use in the research graph."""
    executions = await load_all_executions(
        session, months=months, symbol=symbol, broker_account_id=broker_account_id
    )
    if not executions:
        return {}

    profile = build_trading_profile(executions, period_months=months)
    return profile.per_symbol_stats.get(symbol, {})  # type: ignore[return-value]


async def sync_ibkr_flex_executions(
    session: AsyncSession,
    broker_account_id: uuid.UUID,
    token: str,
    query_id: str,
) -> dict[str, Any]:
    """Fetch IBKR Flex Query XML, parse, persist executions, rebuild trading profile.

    Returns dict with fetched, inserted, profile_snapshot_id.
    Token is never logged.
    """
    ba_repo = BrokerAccountRepository(session)
    repo = IBKRExecutionRepository(session)

    query_id_hash = hashlib.sha256(query_id.encode()).hexdigest()[:12]

    try:
        flex_client = FlexClient.from_settings()
        xml_text = await flex_client.fetch_statement(token, query_id)
        flex_execs = parse_flex_xml(xml_text, query_id_hash=query_id_hash)

        fetched = len(flex_execs)
        inserted = 0
        for ex in flex_execs:
            if await repo.exists_by_exec_id(ex.exec_id, broker_account_id=broker_account_id):
                continue
            # Convert FlexExecution → IBKRExecution for repository
            ibkr_ex = IBKRExecutionSchema(
                exec_id=ex.exec_id,
                account_id_ibkr=ex.account_id_ibkr,
                symbol=ex.symbol,
                exchange=ex.exchange,
                side=ex.side,
                quantity=ex.quantity,
                price=ex.price,
                commission=ex.commission,
                currency=ex.currency,
                executed_at=ex.executed_at,
                order_ref=ex.order_ref,
                raw_json=ex.raw_json,
            )
            await repo.create(ibkr_ex, broker_account_id=broker_account_id)
            inserted += 1

        await ba_repo.mark_sync_success(broker_account_id)
        logger.info(
            "flex_sync_complete",
            extra={
                "fetched": fetched,
                "inserted": inserted,
                "broker_account_id": str(broker_account_id),
                "query_id_hash": query_id_hash,
            },
        )

        # Rebuild trading profile for this broker account
        snapshot = await build_and_save_profile(session, broker_account_id=broker_account_id)
        profile_snapshot_id = str(snapshot.id)

    except IntegrityError as exc:
        await session.rollback()
        await ba_repo.mark_sync_failure(broker_account_id, str(exc))
        raise
    except Exception as exc:
        await ba_repo.mark_sync_failure(broker_account_id, str(exc))
        raise

    return {
        "fetched": fetched,
        "inserted": inserted,
        "profile_snapshot_id": profile_snapshot_id,
    }


async def get_latest_profile(
    session: AsyncSession,
    broker_account_id: uuid.UUID | None = None,
) -> TradingProfileSnapshot | None:
    repo = TradingProfileSnapshotRepository(session)
    if broker_account_id is not None:
        return await repo.latest(broker_account_id=broker_account_id)
    return await repo.latest()
