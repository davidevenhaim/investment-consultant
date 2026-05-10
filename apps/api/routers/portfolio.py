"""Portfolio router — GET/POST/DELETE /api/v1/portfolio + M9.5 trade history endpoints."""

from typing import Any

from core.config import get_settings
from core.responses import api_response
from db.repositories import (
    ManualTradeRepository,
    PortfolioPositionRepository,
    PortfolioSnapshotRepository,
    TradingProfileSnapshotRepository,
)
from db.schemas import (
    IBKRSyncResponse,
    ManualTradeCreate,
    ManualTradeResponse,
    PortfolioAccountResponse,
    PortfolioPositionCreate,
    PortfolioPositionResponse,
    PortfolioSnapshotResponse,
    PortfolioSummaryResponse,
    TradingProfileResponse,
)
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from portfolio.service import (
    build_portfolio_snapshot,
    ensure_default_portfolio,
    refresh_portfolio_prices,
)
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


async def _get_summary(db: AsyncSession, request: Request) -> dict[str, Any]:
    account = await ensure_default_portfolio(db)
    pos_repo = PortfolioPositionRepository(db)
    snap_repo = PortfolioSnapshotRepository(db)
    positions = await pos_repo.list_by_account(account.id)
    latest_snap = await snap_repo.latest(account.id)

    summary = PortfolioSummaryResponse(
        account=PortfolioAccountResponse.model_validate(account),
        snapshot=PortfolioSnapshotResponse.model_validate(latest_snap) if latest_snap else None,
        positions=[PortfolioPositionResponse.model_validate(p) for p in positions],
    )
    return api_response(summary.model_dump(), request)


@router.get("")
async def get_portfolio(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    # ensure_default_portfolio may CREATE the account — commit so it survives
    await ensure_default_portfolio(db)
    await db.commit()
    return await _get_summary(db, request)


@router.post("/positions")
async def upsert_position(
    body: PortfolioPositionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    account = await ensure_default_portfolio(db)
    pos_repo = PortfolioPositionRepository(db)
    await pos_repo.upsert_position(
        account_id=account.id,
        symbol=body.symbol,
        quantity=body.quantity,
        average_cost=body.average_cost,
    )
    await refresh_portfolio_prices(db, account.id)
    await build_portfolio_snapshot(db, account.id)
    await db.commit()  # persist so the next research run's fresh session sees the data
    return await _get_summary(db, request)


@router.delete("/positions/{symbol}")
async def delete_position(
    symbol: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    account = await ensure_default_portfolio(db)
    pos_repo = PortfolioPositionRepository(db)
    removed = await pos_repo.delete_position(account.id, symbol)
    if not removed:
        raise HTTPException(status_code=404, detail=f"{symbol.upper()} not found in portfolio.")
    await build_portfolio_snapshot(db, account.id)
    await db.commit()
    return api_response({"symbol": symbol.upper(), "removed": True}, request)


@router.post("/refresh")
async def refresh_portfolio(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    account = await ensure_default_portfolio(db)
    await refresh_portfolio_prices(db, account.id)
    await build_portfolio_snapshot(db, account.id)
    await db.commit()
    return await _get_summary(db, request)


# ── M9.5: IBKR sync ──────────────────────────────────────────────────────────


@router.post("/sync-ibkr")
async def sync_ibkr(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Fetch IBKR executions and persist new ones. IBKR_ENABLED must be true."""
    cfg = get_settings()
    if not cfg.ibkr_enabled:
        raise HTTPException(
            status_code=503,
            detail="IBKR integration is disabled. Set IBKR_ENABLED=true to enable.",
        )

    from broker.ibkr.client import IBKRClient
    from broker.ibkr.trade_history import fetch_executions
    from portfolio.trade_history_service import sync_ibkr_executions

    async with IBKRClient().connected() as client:
        executions = await fetch_executions(client, months=cfg.ibkr_trade_history_months)

    inserted = await sync_ibkr_executions(db, executions)
    await db.commit()

    result = IBKRSyncResponse(
        inserted=inserted,
        message=f"Synced {len(executions)} executions from IBKR; {inserted} new.",
    )
    return api_response(result.model_dump(), request)


# ── M9.5: Trading profile ─────────────────────────────────────────────────────


@router.get("/trading-profile")
async def get_trading_profile(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the most recent trading profile snapshot."""
    repo = TradingProfileSnapshotRepository(db)
    snapshot = await repo.latest()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No trading profile found. Run a sync first.")
    return api_response(TradingProfileResponse.model_validate(snapshot).model_dump(), request)


@router.post("/trading-profile/rebuild")
async def rebuild_trading_profile(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Recompute and persist a fresh trading profile from current trade history."""
    from portfolio.trade_history_service import build_and_save_profile

    snapshot = await build_and_save_profile(db)
    await db.commit()
    return api_response(TradingProfileResponse.model_validate(snapshot).model_dump(), request)


@router.get("/trading-profile/{symbol}")
async def get_symbol_trading_stats(
    symbol: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return per-symbol trading stats for one ticker."""
    from portfolio.trade_history_service import get_symbol_trading_stats

    stats = await get_symbol_trading_stats(db, symbol.upper())
    if not stats:
        raise HTTPException(
            status_code=404,
            detail=f"No trade history found for {symbol.upper()}.",
        )
    return api_response(stats, request)


# ── M9.5: Trade history CRUD ──────────────────────────────────────────────────


@router.get("/trades")
async def list_trades(
    request: Request,
    symbol: str | None = Query(default=None),
    months: int = Query(default=12, ge=1, le=120),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List combined IBKR + manual trades for the given window."""
    from portfolio.trade_history_service import load_all_executions

    executions = await load_all_executions(db, months=months, symbol=symbol)
    rows = [ex.model_dump() for ex in executions]
    return api_response({"trades": rows, "count": len(rows)}, request)


@router.post("/trades")
async def add_manual_trade(
    body: ManualTradeCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Record a manual (non-IBKR) trade entry."""
    repo = ManualTradeRepository(db)
    row = await repo.create(
        symbol=body.symbol.upper(),
        side=body.side,
        quantity=body.quantity,
        price=body.price,
        executed_at=body.executed_at,
        notes=body.notes,
        source=body.source,
    )
    await db.commit()
    return api_response(ManualTradeResponse.model_validate(row).model_dump(), request)
