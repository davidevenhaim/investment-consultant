from typing import Any

from core.logging import get_logger
from core.responses import api_response
from db.repositories import InvestorProfileRepository
from db.schemas import InvestorProfileResponse, InvestorProfileUpdate
from db.session import get_db
from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies.auth import CurrentUser, get_current_user

router = APIRouter(prefix="/risk-profile", tags=["risk-profile"])
logger = get_logger(__name__)


@router.get("")
async def get_risk_profile(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    repo = InvestorProfileRepository(db)
    profile = await repo.get_default(user_id=current_user.user_id)
    if profile is None:
        profile = await repo.create(
            user_id=current_user.user_id,
            name="default",
            is_active=True,
        )
        await db.commit()
    return api_response(InvestorProfileResponse.model_validate(profile).model_dump(), request)


@router.put("")
async def update_risk_profile(
    body: InvestorProfileUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: CurrentUser = Depends(get_current_user),
) -> dict[str, Any]:
    repo = InvestorProfileRepository(db)
    profile = await repo.get_default(user_id=current_user.user_id)
    if profile is None:
        profile = await repo.create(
            user_id=current_user.user_id,
            name="default",
            is_active=True,
        )

    updates = body.model_dump(exclude_none=True)
    if updates:
        # Convert enum to string value if needed
        if "risk_level" in updates:
            updates["risk_level"] = updates["risk_level"].value
        profile = await repo.update(profile, **updates)
    await db.commit()
    logger.info("risk_profile_updated", updates=list(updates.keys()))
    return api_response(InvestorProfileResponse.model_validate(profile).model_dump(), request)
