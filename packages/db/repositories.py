"""Repository layer — all DB access goes through these classes. No raw queries in routes."""
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from db.enums import ResearchRunStatus, ResearchRunType, TickerRunStatus
from db.models import (
    AuditLog,
    InvestorProfile,
    JobEvent,
    NeutralRecommendation,
    PromptVersion,
    ResearchRun,
    ResearchRunTicker,
    StrategyVersion,
    WatchlistSymbol,
)


class StrategyVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_active(self) -> StrategyVersion | None:
        result = await self._s.execute(
            select(StrategyVersion).where(StrategyVersion.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_by_version(self, version: str) -> StrategyVersion | None:
        result = await self._s.execute(
            select(StrategyVersion).where(StrategyVersion.version == version)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        version: str,
        description: str | None = None,
        scoring_config: dict[str, Any] | None = None,
        risk_policy: dict[str, Any] | None = None,
        is_active: bool = False,
    ) -> StrategyVersion:
        sv = StrategyVersion(
            version=version,
            description=description,
            scoring_config_json=scoring_config or {},
            risk_policy_json=risk_policy or {},
            is_active=is_active,
        )
        self._s.add(sv)
        await self._s.flush()
        await self._s.refresh(sv)
        return sv

    async def activate(self, version_id: uuid.UUID) -> StrategyVersion:
        """Deactivate all others then activate this one. Enforces single-active invariant."""
        await self._s.execute(
            update(StrategyVersion)
            .where(StrategyVersion.id != version_id)
            .values(is_active=False)
        )
        await self._s.execute(
            update(StrategyVersion)
            .where(StrategyVersion.id == version_id)
            .values(is_active=True)
        )
        await self._s.flush()
        result = await self._s.execute(
            select(StrategyVersion).where(StrategyVersion.id == version_id)
        )
        sv = result.scalar_one()
        await self._s.refresh(sv)
        return sv


class PromptVersionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_active(self, name: str) -> PromptVersion | None:
        result = await self._s.execute(
            select(PromptVersion).where(
                PromptVersion.name == name, PromptVersion.is_active.is_(True)
            )
        )
        return result.scalar_one_or_none()

    async def get_by_name_version(self, name: str, version: str) -> PromptVersion | None:
        result = await self._s.execute(
            select(PromptVersion).where(
                PromptVersion.name == name, PromptVersion.version == version
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        name: str,
        version: str,
        prompt_text: str,
        output_schema: dict[str, Any] | None = None,
        is_active: bool = False,
    ) -> PromptVersion:
        pv = PromptVersion(
            name=name,
            version=version,
            prompt_text=prompt_text,
            output_schema_json=output_schema or {},
            is_active=is_active,
        )
        self._s.add(pv)
        await self._s.flush()
        await self._s.refresh(pv)
        return pv


class WatchlistRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def list_active(self) -> list[WatchlistSymbol]:
        result = await self._s.execute(
            select(WatchlistSymbol)
            .where(WatchlistSymbol.is_active.is_(True))
            .order_by(WatchlistSymbol.symbol)
        )
        return list(result.scalars().all())

    async def list_all(self) -> list[WatchlistSymbol]:
        result = await self._s.execute(
            select(WatchlistSymbol).order_by(WatchlistSymbol.symbol)
        )
        return list(result.scalars().all())

    async def get_by_symbol(self, symbol: str) -> WatchlistSymbol | None:
        result = await self._s.execute(
            select(WatchlistSymbol).where(WatchlistSymbol.symbol == symbol.upper())
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        symbol: str,
        company_name: str | None = None,
        exchange: str | None = None,
        asset_type: str = "EQUITY",
        notes: str | None = None,
    ) -> WatchlistSymbol:
        ws = WatchlistSymbol(
            symbol=symbol.upper(),
            company_name=company_name,
            exchange=exchange,
            asset_type=asset_type,
            notes=notes,
        )
        self._s.add(ws)
        await self._s.flush()
        await self._s.refresh(ws)
        return ws

    async def deactivate(self, symbol: str) -> bool:
        result = await self._s.execute(
            select(WatchlistSymbol).where(WatchlistSymbol.symbol == symbol.upper())
        )
        ws = result.scalar_one_or_none()
        if ws is None:
            return False
        ws.is_active = False
        await self._s.flush()
        return True


class InvestorProfileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_default(self) -> InvestorProfile | None:
        result = await self._s.execute(
            select(InvestorProfile)
            .where(InvestorProfile.is_active.is_(True))
            .order_by(InvestorProfile.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, profile_id: uuid.UUID) -> InvestorProfile | None:
        result = await self._s.execute(
            select(InvestorProfile).where(InvestorProfile.id == profile_id)
        )
        return result.scalar_one_or_none()

    async def create(self, **kwargs: Any) -> InvestorProfile:
        profile = InvestorProfile(**kwargs)
        self._s.add(profile)
        await self._s.flush()
        await self._s.refresh(profile)
        return profile

    async def update(self, profile: InvestorProfile, **fields: Any) -> InvestorProfile:
        for k, v in fields.items():
            if v is not None:
                setattr(profile, k, v)
        profile.updated_at = datetime.now(UTC)
        await self._s.flush()
        await self._s.refresh(profile)
        return profile


class ResearchRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(
        self,
        run_type: ResearchRunType,
        strategy_version_id: uuid.UUID | None = None,
        prompt_version_id: uuid.UUID | None = None,
    ) -> ResearchRun:
        run = ResearchRun(
            run_type=run_type.value,
            status=ResearchRunStatus.CREATED.value,
            strategy_version_id=strategy_version_id,
            prompt_version_id=prompt_version_id,
        )
        self._s.add(run)
        await self._s.flush()
        await self._s.refresh(run)
        return run

    async def add_tickers(
        self, run_id: uuid.UUID, symbols: list[str]
    ) -> list[ResearchRunTicker]:
        tickers = [
            ResearchRunTicker(
                research_run_id=run_id,
                symbol=s.upper(),
                status=TickerRunStatus.CREATED.value,
            )
            for s in symbols
        ]
        self._s.add_all(tickers)
        await self._s.flush()
        for t in tickers:
            await self._s.refresh(t)
        return tickers

    async def get_by_id(self, run_id: uuid.UUID) -> ResearchRun | None:
        result = await self._s.execute(
            select(ResearchRun)
            .options(selectinload(ResearchRun.tickers))
            .where(ResearchRun.id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_recent(self, limit: int = 20, offset: int = 0) -> list[ResearchRun]:
        result = await self._s.execute(
            select(ResearchRun)
            .order_by(ResearchRun.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        run_id: uuid.UUID,
        status: ResearchRunStatus,
        error_message: str | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": status.value,
            "updated_at": datetime.now(UTC),
        }
        if status == ResearchRunStatus.RUNNING:
            values["started_at"] = datetime.now(UTC)
        terminal = (
            ResearchRunStatus.COMPLETED, ResearchRunStatus.FAILED, ResearchRunStatus.CANCELLED
        )
        if status in terminal:
            values["finished_at"] = datetime.now(UTC)
        if error_message:
            values["error_message"] = error_message
        await self._s.execute(
            update(ResearchRun).where(ResearchRun.id == run_id).values(**values)
        )
        await self._s.flush()


class RecommendationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_latest_per_symbol(
        self, symbols: list[str] | None = None
    ) -> list[NeutralRecommendation]:
        """Return the most recent neutral recommendation for each symbol."""
        from sqlalchemy import func as sqlfunc

        subq = (
            select(
                NeutralRecommendation.symbol,
                sqlfunc.max(NeutralRecommendation.as_of_time).label("max_time"),
            )
            .group_by(NeutralRecommendation.symbol)
            .subquery()
        )
        q = select(NeutralRecommendation).join(
            subq,
            (NeutralRecommendation.symbol == subq.c.symbol)
            & (NeutralRecommendation.as_of_time == subq.c.max_time),
        )
        if symbols:
            q = q.where(NeutralRecommendation.symbol.in_([s.upper() for s in symbols]))
        result = await self._s.execute(q)
        return list(result.scalars().all())


class JobEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(
        self,
        entity_type: str,
        event_type: str,
        entity_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> JobEvent:
        ev = JobEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            event_type=event_type,
            payload_json=payload or {},
            correlation_id=correlation_id,
        )
        self._s.add(ev)
        await self._s.flush()
        return ev


class AuditLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(
        self,
        event_type: str,
        entity_type: str,
        actor: str = "system",
        entity_id: uuid.UUID | None = None,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
    ) -> AuditLog:
        log = AuditLog(
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor=actor,
            payload_json=payload or {},
            correlation_id=correlation_id,
        )
        self._s.add(log)
        await self._s.flush()
        return log
