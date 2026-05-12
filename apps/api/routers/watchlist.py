from typing import Any

from core.logging import get_logger
from core.responses import api_response
from db.repositories import WatchlistRepository
from db.schemas import WatchlistSymbolCreate, WatchlistSymbolResponse
from db.session import get_db
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
logger = get_logger(__name__)


@router.get("")
async def list_watchlist(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    repo = WatchlistRepository(db)
    symbols = await repo.list_active(user_id=current_user.user_id)
    return api_response(
        [WatchlistSymbolResponse.model_validate(s).model_dump() for s in symbols],
        request,
    )


@router.post("", status_code=201)
async def add_to_watchlist(
    body: WatchlistSymbolCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    repo = WatchlistRepository(db)
    existing = await repo.get_by_symbol(body.symbol, user_id=current_user.user_id)
    if existing:
        if existing.is_active:
            raise HTTPException(
                status_code=409, detail=f"{body.symbol.upper()} already on watchlist"
            )
        # Reactivate if was deactivated
        existing.is_active = True
        await db.flush()
        await db.refresh(existing)
        await db.commit()
        return api_response(WatchlistSymbolResponse.model_validate(existing).model_dump(), request)

    symbol = await repo.create(
        symbol=body.symbol,
        user_id=current_user.user_id,
        company_name=body.company_name,
        exchange=body.exchange,
        asset_type=body.asset_type.value,
        notes=body.notes,
    )
    await db.commit()
    logger.info("watchlist_symbol_added", symbol=symbol.symbol)
    return api_response(WatchlistSymbolResponse.model_validate(symbol).model_dump(), request)


@router.delete("/{symbol}", status_code=200)
async def remove_from_watchlist(
    symbol: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    repo = WatchlistRepository(db)
    removed = await repo.deactivate(symbol, user_id=current_user.user_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"{symbol.upper()} not found on watchlist")
    await db.commit()
    return api_response({"symbol": symbol.upper(), "removed": True}, request)
