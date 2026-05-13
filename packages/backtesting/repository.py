"""Repository for recommendation_outcomes and learning_events."""

from __future__ import annotations

from typing import TYPE_CHECKING

from db.models import LearningEvent, RecommendationOutcome
from sqlalchemy import select, update

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession


class RecommendationOutcomeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        symbol: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[RecommendationOutcome]:
        q = (
            select(RecommendationOutcome)
            .where(RecommendationOutcome.user_id == user_id)
            .order_by(RecommendationOutcome.created_at.desc())
            .limit(limit)
        )
        if symbol:
            q = q.where(RecommendationOutcome.symbol == symbol.upper())
        if status:
            q = q.where(RecommendationOutcome.outcome_status == status.upper())
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def get_by_id_for_user(
        self, outcome_id: uuid.UUID, user_id: uuid.UUID
    ) -> RecommendationOutcome | None:
        result = await self._s.execute(
            select(RecommendationOutcome).where(
                RecommendationOutcome.id == outcome_id,
                RecommendationOutcome.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()


class LearningEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def list_for_user(
        self,
        user_id: uuid.UUID,
        symbol: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[LearningEvent]:
        q = (
            select(LearningEvent)
            .where(LearningEvent.user_id == user_id)
            .order_by(LearningEvent.created_at.desc())
            .limit(limit)
        )
        if symbol:
            q = q.where(LearningEvent.symbol == symbol.upper())
        if status:
            q = q.where(LearningEvent.status == status.upper())
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def get_by_id_for_user(
        self, event_id: uuid.UUID, user_id: uuid.UUID
    ) -> LearningEvent | None:
        result = await self._s.execute(
            select(LearningEvent).where(
                LearningEvent.id == event_id,
                LearningEvent.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_status(
        self, event_id: uuid.UUID, user_id: uuid.UUID, new_status: str
    ) -> LearningEvent | None:
        """Update status; returns updated row or None if not found / wrong user."""
        from datetime import UTC, datetime

        await self._s.execute(
            update(LearningEvent)
            .where(LearningEvent.id == event_id, LearningEvent.user_id == user_id)
            .values(status=new_status, updated_at=datetime.now(UTC))
        )
        await self._s.flush()
        return await self.get_by_id_for_user(event_id, user_id)
