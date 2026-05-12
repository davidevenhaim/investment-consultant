"""Portfolio router — M9 portfolio + M9.5 trade history + M9.6 broker accounts."""

import uuid
from typing import Any

from core.config import get_settings
from core.errors import IBKRConnectionError
from core.responses import api_response
from db.repositories import (
    BrokerAccountRepository,
    ManualTradeRepository,
    PortfolioPositionRepository,
    PortfolioSnapshotRepository,
    TradingProfileSnapshotRepository,
)
from db.schemas import (
    BrokerAccountCreate,
    BrokerAccountResponse,
    BrokerAccountUpdate,
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

from apps.api.dependencies.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _active_broker_account_id(
    db: AsyncSession,
    user_id: uuid.UUID,
) -> uuid.UUID | None:
    """Return the active default broker account ID, or None if none exists."""
    ba_repo = BrokerAccountRepository(db)
    account = await ba_repo.get_active_default(user_id=user_id)
    return account.id if account is not None else None


async def _get_summary(
    db: AsyncSession,
    request: Request,
    user_id: uuid.UUID,
) -> dict[str, Any]:
    account = await ensure_default_portfolio(db, user_id=user_id)
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


async def _run_ibkr_sync(
    db: AsyncSession,
    request: Request,
    user_id: uuid.UUID,
    broker_account_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Shared sync logic for /sync-ibkr and /broker-accounts/{id}/sync-ibkr.

    IBKR fetch runs in an isolated thread with its own event loop via
    asyncio.to_thread + fetch_executions_isolated. This avoids the
    "Future attached to a different loop" error that occurs when ib_insync
    runs inside the Uvicorn/FastAPI event loop.

    The DB writes stay in the normal async session after the isolated fetch returns.
    """
    import asyncio

    from broker.ibkr.client import IBKRClient
    from broker.ibkr.sync_runner import fetch_executions_isolated
    from portfolio.trade_history_service import sync_ibkr_executions

    cfg = get_settings()
    ba_repo = BrokerAccountRepository(db)

    if broker_account_id is not None:
        broker_account = await ba_repo.get_by_id_for_user(broker_account_id, user_id)
        if broker_account is None:
            raise HTTPException(status_code=404, detail="Broker account not found.")
        client = IBKRClient.from_broker_account(broker_account)
    else:
        # ensure_dev_default creates the account from current env vars (ibkr_host/port/client_id),
        # so from_broker_account produces the same config as the old from_settings() path.
        broker_account = await ba_repo.ensure_dev_default(user_id=user_id)
        await db.commit()
        client = IBKRClient.from_broker_account(broker_account)

    ba_id = broker_account.id
    ibkr_config = client.config  # IBKRConnectionConfig — safe to pass into thread

    try:
        # Run the IBKR fetch in a worker thread with its own event loop.
        # asyncio.run() inside the thread creates a fresh loop; ib_insync
        # futures never touch the Uvicorn loop.
        executions = await asyncio.to_thread(
            fetch_executions_isolated,
            ibkr_config,
            cfg.ibkr_trade_history_months,
        )
        inserted = await sync_ibkr_executions(db, executions, broker_account_id=ba_id)
        await db.commit()
    except IBKRConnectionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result = IBKRSyncResponse(
        inserted=inserted,
        message=f"Synced {len(executions)} executions from IBKR; {inserted} new.",
    )
    return api_response(result.model_dump(), request)


# ── Portfolio CRUD ────────────────────────────────────────────────────────────


@router.get("")
async def get_portfolio(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    await ensure_default_portfolio(db, user_id=current_user.user_id)
    await db.commit()
    return await _get_summary(db, request, current_user.user_id)


@router.post("/positions")
async def upsert_position(
    body: PortfolioPositionCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    account = await ensure_default_portfolio(db, user_id=current_user.user_id)
    pos_repo = PortfolioPositionRepository(db)
    await pos_repo.upsert_position(
        account_id=account.id,
        symbol=body.symbol,
        quantity=body.quantity,
        average_cost=body.average_cost,
    )
    await refresh_portfolio_prices(db, account.id)
    await build_portfolio_snapshot(db, account.id)
    await db.commit()
    return await _get_summary(db, request, current_user.user_id)


@router.delete("/positions/{symbol}")
async def delete_position(
    symbol: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    account = await ensure_default_portfolio(db, user_id=current_user.user_id)
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
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    account = await ensure_default_portfolio(db, user_id=current_user.user_id)
    await refresh_portfolio_prices(db, account.id)
    await build_portfolio_snapshot(db, account.id)
    await db.commit()
    return await _get_summary(db, request, current_user.user_id)


# ── M9.5: IBKR sync (global dev path) ────────────────────────────────────────


@router.post("/sync-ibkr")
async def sync_ibkr(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Sync IBKR executions via the default dev broker account.

    Requires IBKR_ENABLED=true and TWS/IB Gateway running on host.
    """
    cfg = get_settings()
    if not cfg.ibkr_enabled:
        raise HTTPException(
            status_code=503,
            detail="IBKR integration is disabled. Set IBKR_ENABLED=true to enable.",
        )
    return await _run_ibkr_sync(db, request, user_id=current_user.user_id)


# ── M9.5: Trading profile ─────────────────────────────────────────────────────


@router.get("/trading-profile")
async def get_trading_profile(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    repo = TradingProfileSnapshotRepository(db)
    ba_id = await _active_broker_account_id(db, current_user.user_id)
    if ba_id is None:
        raise HTTPException(status_code=404, detail="No trading profile found.")
    snapshot = await repo.latest(broker_account_id=ba_id)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No trading profile found.")
    return api_response(TradingProfileResponse.model_validate(snapshot).model_dump(), request)


@router.post("/trading-profile/rebuild")
async def rebuild_trading_profile(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    from portfolio.trade_history_service import build_and_save_profile

    ba_repo = BrokerAccountRepository(db)
    broker_account = await ba_repo.ensure_dev_default(user_id=current_user.user_id)
    ba_id = broker_account.id
    snapshot = await build_and_save_profile(db, broker_account_id=ba_id)
    await db.commit()
    return api_response(TradingProfileResponse.model_validate(snapshot).model_dump(), request)


@router.get("/trading-profile/{symbol}")
async def get_symbol_trading_stats(
    symbol: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    from portfolio.trade_history_service import get_symbol_trading_stats as _get_stats

    ba_id = await _active_broker_account_id(db, current_user.user_id)
    if ba_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"No trade history found for {symbol.upper()}.",
        )
    stats = await _get_stats(db, symbol.upper(), broker_account_id=ba_id)
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
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    from portfolio.trade_history_service import load_all_executions

    ba_id = await _active_broker_account_id(db, current_user.user_id)
    if ba_id is None:
        return api_response({"trades": [], "count": 0}, request)
    executions = await load_all_executions(
        db, months=months, symbol=symbol, broker_account_id=ba_id
    )
    rows = [ex.model_dump() for ex in executions]
    return api_response({"trades": rows, "count": len(rows)}, request)


@router.post("/trades")
async def add_manual_trade(
    body: ManualTradeCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    repo = ManualTradeRepository(db)
    ba_repo = BrokerAccountRepository(db)
    broker_account = await ba_repo.ensure_dev_default(user_id=current_user.user_id)
    row = await repo.create(
        symbol=body.symbol.upper(),
        side=body.side,
        quantity=body.quantity,
        price=body.price,
        executed_at=body.executed_at,
        notes=body.notes,
        source=body.source,
        broker_account_id=broker_account.id,
    )
    await db.commit()
    return api_response(ManualTradeResponse.model_validate(row).model_dump(), request)


# ── M9.6: Broker accounts ─────────────────────────────────────────────────────


@router.get("/broker-accounts")
async def list_broker_accounts(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    repo = BrokerAccountRepository(db)
    accounts = await repo.list_active(user_id=current_user.user_id)
    return api_response(
        [BrokerAccountResponse.model_validate(a).model_dump() for a in accounts],
        request,
    )


@router.post("/broker-accounts")
async def create_broker_account(
    body: BrokerAccountCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    repo = BrokerAccountRepository(db)
    account = await repo.create(
        provider=body.provider,
        display_name=body.display_name,
        connection_mode=body.connection_mode,
        host=body.host,
        port=body.port,
        client_id=body.client_id,
        readonly=body.readonly,
        is_active=body.is_active,
        user_id=current_user.user_id,
        external_account_id=body.external_account_id,
        metadata_json=body.metadata_json,
    )
    await db.commit()
    return api_response(BrokerAccountResponse.model_validate(account).model_dump(), request)


@router.get("/broker-accounts/{broker_account_id}")
async def get_broker_account(
    broker_account_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    repo = BrokerAccountRepository(db)
    account = await repo.get_by_id_for_user(broker_account_id, current_user.user_id)
    if account is None:
        raise HTTPException(status_code=404, detail="Broker account not found.")
    return api_response(BrokerAccountResponse.model_validate(account).model_dump(), request)


@router.patch("/broker-accounts/{broker_account_id}")
async def update_broker_account(
    broker_account_id: uuid.UUID,
    body: BrokerAccountUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    repo = BrokerAccountRepository(db)
    existing = await repo.get_by_id_for_user(broker_account_id, current_user.user_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Broker account not found.")

    updates = body.model_dump(exclude_none=True)
    account = await repo.update(broker_account_id, **updates)
    await db.commit()
    return api_response(
        BrokerAccountResponse.model_validate(account).model_dump(), request
    )


@router.post("/broker-accounts/{broker_account_id}/sync-ibkr")
async def sync_ibkr_for_account(
    broker_account_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Sync IBKR executions for a specific broker account."""
    cfg = get_settings()
    if not cfg.ibkr_enabled:
        raise HTTPException(
            status_code=503,
            detail="IBKR integration is disabled. Set IBKR_ENABLED=true to enable.",
        )
    return await _run_ibkr_sync(
        db,
        request,
        user_id=current_user.user_id,
        broker_account_id=broker_account_id,
    )


# ── M9.7: Flex Query sync ─────────────────────────────────────────────────────


def _get_flex_credentials(cfg: Any, broker_account: Any) -> tuple[str, str]:
    """Load Flex token and query_id.

    Priority:
      1. metadata_json["flex_token_env"] / ["flex_query_id_env"] → resolve env var name
      2. Global settings (IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID)

    Never accept raw token in request body.
    """
    import os  # noqa: PLC0415

    token = ""
    query_id = ""

    if broker_account is not None:
        meta = broker_account.metadata_json or {}
        token_env = meta.get("flex_token_env")
        query_env = meta.get("flex_query_id_env")
        if token_env:
            token = os.environ.get(str(token_env), "")
        if query_env:
            query_id = os.environ.get(str(query_env), "")

    # Fall back to global settings
    if not token:
        token = cfg.ibkr_flex_token
    if not query_id:
        query_id = cfg.ibkr_flex_query_id

    return token, query_id


@router.post("/sync-flex")
async def sync_flex_global(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Sync historical IBKR executions via Flex Query for the default dev account.

    Requires IBKR_FLEX_ENABLED=true and valid IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID.
    """
    cfg = get_settings()
    if not cfg.ibkr_flex_enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "IBKR Flex Query is disabled. "
                "Set IBKR_FLEX_ENABLED=true and configure token/query_id."
            ),
        )

    from db.repositories import BrokerAccountRepository  # noqa: PLC0415

    ba_repo = BrokerAccountRepository(db)
    broker_account = await ba_repo.ensure_dev_default(user_id=current_user.user_id)
    await db.commit()

    token, query_id = _get_flex_credentials(cfg, broker_account)
    if not token or not query_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Flex token or query_id missing. "
                "Set IBKR_FLEX_TOKEN and IBKR_FLEX_QUERY_ID in environment."
            ),
        )

    from core.errors import IBKRFlexError  # noqa: PLC0415
    from portfolio.trade_history_service import sync_ibkr_flex_executions  # noqa: PLC0415

    try:
        result = await sync_ibkr_flex_executions(
            db, broker_account.id, token, query_id
        )
        await db.commit()
    except IBKRFlexError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return api_response(result, request)


@router.post("/broker-accounts/{broker_account_id}/sync-flex")
async def sync_flex_for_account(
    broker_account_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    """Sync historical IBKR executions via Flex Query for a specific broker account."""
    cfg = get_settings()
    if not cfg.ibkr_flex_enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "IBKR Flex Query is disabled. "
                "Set IBKR_FLEX_ENABLED=true and configure token/query_id."
            ),
        )

    from db.repositories import BrokerAccountRepository  # noqa: PLC0415

    ba_repo = BrokerAccountRepository(db)
    broker_account = await ba_repo.get_by_id_for_user(
        broker_account_id,
        current_user.user_id,
    )
    if broker_account is None:
        raise HTTPException(status_code=404, detail="Broker account not found.")

    token, query_id = _get_flex_credentials(cfg, broker_account)
    if not token or not query_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "Flex token or query_id missing for this broker account. "
                "Set flex_token_env / flex_query_id_env in metadata_json, "
                "or set IBKR_FLEX_TOKEN / IBKR_FLEX_QUERY_ID globally."
            ),
        )

    from core.errors import IBKRFlexError  # noqa: PLC0415
    from portfolio.trade_history_service import sync_ibkr_flex_executions  # noqa: PLC0415

    try:
        result = await sync_ibkr_flex_executions(
            db, broker_account_id, token, query_id
        )
        await db.commit()
    except IBKRFlexError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return api_response(result, request)
