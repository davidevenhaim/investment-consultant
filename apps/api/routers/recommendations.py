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
    rec_repo = RecommendationRepository(db)
    wl_repo = WatchlistRepository(db)

    # All recs from the single latest research run — prevents symbol bleed across runs
    recs = await rec_repo.get_from_latest_run()

    if recs:
        neutral_ids = [r.id for r in recs]
        personalized_by_neutral = await rec_repo.get_latest_personalized_by_neutral_ids(
            neutral_ids
        )
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
    else:
        # No completed runs yet — return watchlist symbols with null recs
        symbols = [s.symbol for s in await wl_repo.list_active()]
        result = [
            LatestRecommendationResponse(symbol=s, neutral=None, personalized=None).model_dump()
            for s in symbols
        ]

    return api_response(result, request)
