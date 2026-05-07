from typing import Any

from core.responses import api_response
from db.repositories import RecommendationRepository, WatchlistRepository
from db.schemas import LatestRecommendationResponse, NeutralRecommendationResponse
from db.session import get_db
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


@router.get("/latest")
async def latest_recommendations(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    wl_repo = WatchlistRepository(db)
    rec_repo = RecommendationRepository(db)

    symbols = [s.symbol for s in await wl_repo.list_active()]
    recs = await rec_repo.get_latest_per_symbol(symbols if symbols else None)
    rec_by_symbol = {r.symbol: r for r in recs}

    result = []
    for symbol in symbols:
        rec = rec_by_symbol.get(symbol)
        result.append(
            LatestRecommendationResponse(
                symbol=symbol,
                neutral=NeutralRecommendationResponse.model_validate(rec) if rec else None,
            ).model_dump()
        )

    # If no watchlist, return whatever recs exist
    if not symbols and recs:
        result = [
            LatestRecommendationResponse(
                symbol=r.symbol,
                neutral=NeutralRecommendationResponse.model_validate(r),
            ).model_dump()
            for r in recs
        ]

    return api_response(result, request)
