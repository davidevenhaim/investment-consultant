from typing import Any

from core.responses import api_response
from db.repositories import RecommendationRepository, WatchlistRepository
from db.schemas import (
    LatestRecommendationResponse,
    NeutralRecommendationResponse,
    PersonalizedRecommendationResponse,
)
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

    # Load personalized recs for each neutral rec
    neutral_ids = [r.id for r in recs]
    personalized_by_neutral = await rec_repo.get_latest_personalized_by_neutral_ids(neutral_ids)

    result = []
    for symbol in symbols:
        neutral = rec_by_symbol.get(symbol)
        pers = personalized_by_neutral.get(neutral.id) if neutral else None
        result.append(
            LatestRecommendationResponse(
                symbol=symbol,
                neutral=NeutralRecommendationResponse.model_validate(neutral) if neutral else None,
                personalized=(
                    PersonalizedRecommendationResponse.model_validate(pers) if pers else None
                ),
            ).model_dump()
        )

    # If no watchlist, return whatever recs exist
    if not symbols and recs:
        result = []
        for r in recs:
            pers = personalized_by_neutral.get(r.id)
            result.append(
                LatestRecommendationResponse(
                    symbol=r.symbol,
                    neutral=NeutralRecommendationResponse.model_validate(r),
                    personalized=(
                        PersonalizedRecommendationResponse.model_validate(pers) if pers else None
                    ),
                ).model_dump()
            )

    return api_response(result, request)
