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
    BrokerAccount,
    IBKRExecution,
    InvestorProfile,
    JobEvent,
    ManualTrade,
    MemoryIndexEvent,
    NeutralRecommendation,
    PersonalizedRecommendation,
    PortfolioAccount,
    PortfolioPosition,
    PortfolioSnapshot,
    PromptVersion,
    ResearchRun,
    ResearchRunTicker,
    StrategyVersion,
    TradingProfileSnapshot,
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
            update(StrategyVersion).where(StrategyVersion.id != version_id).values(is_active=False)
        )
        await self._s.execute(
            update(StrategyVersion).where(StrategyVersion.id == version_id).values(is_active=True)
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
        result = await self._s.execute(select(WatchlistSymbol).order_by(WatchlistSymbol.symbol))
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

    async def add_tickers(self, run_id: uuid.UUID, symbols: list[str]) -> list[ResearchRunTicker]:
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
            select(ResearchRun).order_by(ResearchRun.created_at.desc()).limit(limit).offset(offset)
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
            ResearchRunStatus.COMPLETED,
            ResearchRunStatus.FAILED,
            ResearchRunStatus.CANCELLED,
        )
        if status in terminal:
            values["finished_at"] = datetime.now(UTC)
        if error_message:
            values["error_message"] = error_message
        await self._s.execute(update(ResearchRun).where(ResearchRun.id == run_id).values(**values))
        await self._s.flush()

    async def update_ticker_status(
        self,
        ticker_id: uuid.UUID,
        status: TickerRunStatus,
        error_message: str | None = None,
    ) -> None:
        values: dict[str, Any] = {
            "status": status.value,
            "updated_at": datetime.now(UTC),
        }
        if status == TickerRunStatus.RUNNING:
            values["started_at"] = datetime.now(UTC)
        if status in (TickerRunStatus.COMPLETED, TickerRunStatus.FAILED):
            values["finished_at"] = datetime.now(UTC)
        if error_message:
            values["error_message"] = error_message
        await self._s.execute(
            update(ResearchRunTicker).where(ResearchRunTicker.id == ticker_id).values(**values)
        )
        await self._s.flush()


class RecommendationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_latest_per_symbol(
        self, symbols: list[str] | None = None
    ) -> list[NeutralRecommendation]:
        """Return the most recent neutral recommendation for each symbol.

        NOTE: may mix recs from different runs. Prefer get_from_latest_run()
        when you want all recs from the single latest run.
        """
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

    async def get_from_latest_run(
        self, symbols: list[str] | None = None
    ) -> list[NeutralRecommendation]:
        """Return all neutral recommendations from the single most recent COMPLETED research run.

        Filters to COMPLETED runs only — FAILED/RUNNING runs are ignored even if newer.
        Scopes results to one run, preventing symbol bleed across runs.
        """
        from sqlalchemy import func as sqlfunc

        # Find the research_run_id with most recent as_of_time, COMPLETED runs only
        latest_run_id_subq = (
            select(NeutralRecommendation.research_run_id)
            .join(ResearchRun, ResearchRun.id == NeutralRecommendation.research_run_id)
            .where(ResearchRun.status == ResearchRunStatus.COMPLETED.value)
            .group_by(NeutralRecommendation.research_run_id)
            .order_by(sqlfunc.max(NeutralRecommendation.as_of_time).desc())
            .limit(1)
            .scalar_subquery()
        )
        q = select(NeutralRecommendation).where(
            NeutralRecommendation.research_run_id == latest_run_id_subq
        )
        if symbols:
            q = q.where(NeutralRecommendation.symbol.in_([s.upper() for s in symbols]))
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def get_latest_personalized_by_neutral_ids(
        self, neutral_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, PersonalizedRecommendation]:
        """Return most recent personalized rec for each neutral_recommendation_id."""
        if not neutral_ids:
            return {}
        from sqlalchemy import func as sqlfunc

        subq = (
            select(
                PersonalizedRecommendation.neutral_recommendation_id,
                sqlfunc.max(PersonalizedRecommendation.created_at).label("max_created"),
            )
            .where(PersonalizedRecommendation.neutral_recommendation_id.in_(neutral_ids))
            .group_by(PersonalizedRecommendation.neutral_recommendation_id)
            .subquery()
        )
        nr_id_col = PersonalizedRecommendation.neutral_recommendation_id
        q = select(PersonalizedRecommendation).join(
            subq,
            (nr_id_col == subq.c.neutral_recommendation_id)
            & (PersonalizedRecommendation.created_at == subq.c.max_created),
        )
        result = await self._s.execute(q)
        rows = result.scalars().all()
        return {r.neutral_recommendation_id: r for r in rows}


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


class MemoryIndexEventRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(
        self,
        entity_type: str,
        status: str,
        entity_id: uuid.UUID | None = None,
        symbol: str | None = None,
        collection_name: str = "",
        chroma_document_id: str | None = None,
        error_message: str | None = None,
    ) -> MemoryIndexEvent:
        ev = MemoryIndexEvent(
            entity_type=entity_type,
            entity_id=entity_id,
            symbol=symbol,
            collection_name=collection_name,
            chroma_document_id=chroma_document_id,
            status=status,
            error_message=error_message,
        )
        self._s.add(ev)
        await self._s.flush()
        return ev


class PortfolioAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_active(self) -> list[PortfolioAccount]:
        result = await self._s.execute(
            select(PortfolioAccount)
            .where(PortfolioAccount.is_active.is_(True))
            .order_by(PortfolioAccount.created_at)
        )
        return list(result.scalars().all())

    async def get_default(self) -> PortfolioAccount | None:
        result = await self._s.execute(
            select(PortfolioAccount)
            .where(PortfolioAccount.is_active.is_(True))
            .order_by(PortfolioAccount.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        name: str,
        account_type: str = "MANUAL",
        base_currency: str = "USD",
        cash_balance: float = 0.0,
    ) -> PortfolioAccount:
        acc = PortfolioAccount(
            name=name,
            account_type=account_type,
            base_currency=base_currency,
            cash_balance=cash_balance,
            is_active=True,
        )
        self._s.add(acc)
        await self._s.flush()
        await self._s.refresh(acc)
        return acc

    async def get_or_create_default(self) -> PortfolioAccount:
        existing = await self.get_default()
        if existing is not None:
            return existing
        return await self.create(name="Default Manual Portfolio", cash_balance=10000.0)

    async def update_cash(self, account_id: uuid.UUID, cash_balance: float) -> None:
        await self._s.execute(
            update(PortfolioAccount)
            .where(PortfolioAccount.id == account_id)
            .values(cash_balance=cash_balance, updated_at=datetime.now(UTC))
        )
        await self._s.flush()


class PortfolioPositionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def list_by_account(self, account_id: uuid.UUID) -> list[PortfolioPosition]:
        result = await self._s.execute(
            select(PortfolioPosition)
            .where(PortfolioPosition.account_id == account_id)
            .order_by(PortfolioPosition.symbol)
        )
        return list(result.scalars().all())

    async def get_by_symbol(
        self, account_id: uuid.UUID, symbol: str
    ) -> PortfolioPosition | None:
        result = await self._s.execute(
            select(PortfolioPosition).where(
                PortfolioPosition.account_id == account_id,
                PortfolioPosition.symbol == symbol.upper(),
            )
        )
        return result.scalar_one_or_none()

    async def upsert_position(
        self,
        account_id: uuid.UUID,
        symbol: str,
        quantity: float,
        average_cost: float | None = None,
        current_price: float | None = None,
    ) -> PortfolioPosition:
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        now = datetime.now(UTC)
        market_value = (quantity * current_price) if current_price is not None else None
        cost_basis = (quantity * average_cost) if average_cost is not None else None
        unrealized_pnl: float | None = None
        unrealized_pnl_pct: float | None = None
        if market_value is not None and cost_basis is not None and cost_basis != 0:
            unrealized_pnl = market_value - cost_basis
            unrealized_pnl_pct = unrealized_pnl / cost_basis

        row: dict[str, Any] = {
            "account_id": account_id,
            "symbol": symbol.upper(),
            "quantity": quantity,
            "average_cost": average_cost,
            "current_price": current_price,
            "market_value": market_value,
            "cost_basis": cost_basis,
            "unrealized_pnl": unrealized_pnl,
            "unrealized_pnl_pct": unrealized_pnl_pct,
            "weight": None,
            "as_of_time": now,
        }
        stmt = (
            pg_insert(PortfolioPosition)
            .values([row])
            .on_conflict_do_update(
                constraint="uq_position_account_symbol",
                set_={
                    "quantity": row["quantity"],
                    "average_cost": row["average_cost"],
                    "current_price": row["current_price"],
                    "market_value": row["market_value"],
                    "cost_basis": row["cost_basis"],
                    "unrealized_pnl": row["unrealized_pnl"],
                    "unrealized_pnl_pct": row["unrealized_pnl_pct"],
                    "as_of_time": row["as_of_time"],
                    "updated_at": now,
                },
            )
        )
        await self._s.execute(stmt)
        await self._s.flush()
        # Re-query to get the fresh row (identity map may have stale data after upsert)
        result = await self._s.execute(
            select(PortfolioPosition).where(
                PortfolioPosition.account_id == account_id,
                PortfolioPosition.symbol == symbol.upper(),
            )
        )
        pos = result.scalar_one()
        await self._s.refresh(pos)
        return pos

    async def delete_position(self, account_id: uuid.UUID, symbol: str) -> bool:
        from sqlalchemy import delete as sa_delete

        existing = await self.get_by_symbol(account_id, symbol)
        if existing is None:
            return False
        await self._s.execute(
            sa_delete(PortfolioPosition).where(
                PortfolioPosition.account_id == account_id,
                PortfolioPosition.symbol == symbol.upper(),
            )
        )
        await self._s.flush()
        return True

    async def update_weights(
        self, account_id: uuid.UUID, total_equity: float
    ) -> None:
        """Recompute weight for each position given total_equity."""
        positions = await self.list_by_account(account_id)
        now = datetime.now(UTC)
        for pos in positions:
            if pos.market_value is not None and total_equity > 0:
                pos.weight = float(pos.market_value) / total_equity
            else:
                pos.weight = None
            pos.updated_at = now
        await self._s.flush()


class PortfolioSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def latest(self, account_id: uuid.UUID) -> PortfolioSnapshot | None:
        result = await self._s.execute(
            select(PortfolioSnapshot)
            .where(PortfolioSnapshot.account_id == account_id)
            .order_by(PortfolioSnapshot.as_of_time.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create_snapshot(
        self,
        account_id: uuid.UUID,
        positions: list[PortfolioPosition],
        cash_balance: float,
    ) -> PortfolioSnapshot:
        now = datetime.now(UTC)
        total_market_value = sum(
            float(p.market_value) for p in positions if p.market_value is not None
        )
        total_equity = total_market_value + cash_balance

        weights = [
            float(p.market_value) / total_equity
            if p.market_value is not None and total_equity > 0
            else 0.0
            for p in positions
        ]
        max_weight = max(weights) if weights else None

        top_positions_raw = [
            {
                "symbol": p.symbol,
                "weight": round(float(p.market_value) / total_equity, 4)
                if p.market_value and total_equity > 0
                else 0.0,
                "market_value": float(p.market_value) if p.market_value else None,
            }
            for p in positions
        ]
        top_positions = sorted(
            top_positions_raw,
            key=lambda x: float(x["weight"]),  # type: ignore[arg-type]
            reverse=True,
        )[:5]

        concentration = max_weight or 0.0
        cash_pct = cash_balance / total_equity if total_equity > 0 else 1.0
        largest = (
            max(positions, key=lambda p: float(p.market_value or 0)).symbol
            if positions
            else None
        )
        risk_metrics: dict[str, Any] = {
            "concentration_score": round(concentration, 4),
            "cash_pct": round(cash_pct, 4),
            "largest_position_symbol": largest,
            "largest_position_weight": round(max_weight, 4) if max_weight else None,
        }

        snap = PortfolioSnapshot(
            account_id=account_id,
            total_market_value=total_market_value,
            cash_balance=cash_balance,
            total_equity=total_equity,
            number_of_positions=len(positions),
            max_position_weight=max_weight,
            top_positions_json=top_positions,
            sector_exposure_json={},
            risk_metrics_json=risk_metrics,
            as_of_time=now,
        )
        self._s.add(snap)
        await self._s.flush()
        await self._s.refresh(snap)
        return snap


class IBKRExecutionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def exists_by_exec_id(
        self, exec_id: str, broker_account_id: uuid.UUID | None = None
    ) -> bool:
        q = select(IBKRExecution.id).where(IBKRExecution.exec_id == exec_id)
        if broker_account_id is not None:
            q = q.where(IBKRExecution.broker_account_id == broker_account_id)
        result = await self._s.execute(q)
        return result.scalar_one_or_none() is not None

    async def create(
        self, ex: Any, broker_account_id: uuid.UUID | None = None
    ) -> IBKRExecution:
        row = IBKRExecution(
            broker_account_id=broker_account_id,
            account_id_ibkr=ex.account_id_ibkr,
            exec_id=ex.exec_id,
            symbol=ex.symbol,
            exchange=ex.exchange,
            side=ex.side,
            quantity=ex.quantity,
            price=ex.price,
            commission=ex.commission,
            currency=ex.currency,
            executed_at=ex.executed_at,
            order_ref=ex.order_ref,
            raw_json=ex.raw_json or {},
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return row

    async def list_since(
        self,
        since: datetime,
        symbol: str | None = None,
        broker_account_id: uuid.UUID | None = None,
    ) -> list[IBKRExecution]:
        q = select(IBKRExecution).where(IBKRExecution.executed_at >= since)
        if symbol:
            q = q.where(IBKRExecution.symbol == symbol)
        if broker_account_id is not None:
            q = q.where(IBKRExecution.broker_account_id == broker_account_id)
        q = q.order_by(IBKRExecution.executed_at)
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def list_by_symbol(
        self, symbol: str, broker_account_id: uuid.UUID | None = None
    ) -> list[IBKRExecution]:
        q = (
            select(IBKRExecution)
            .where(IBKRExecution.symbol == symbol)
            .order_by(IBKRExecution.executed_at)
        )
        if broker_account_id is not None:
            q = q.where(IBKRExecution.broker_account_id == broker_account_id)
        result = await self._s.execute(q)
        return list(result.scalars().all())


class ManualTradeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def create(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        executed_at: datetime,
        notes: str | None = None,
        source: str = "manual",
        broker_account_id: uuid.UUID | None = None,
    ) -> ManualTrade:
        row = ManualTrade(
            broker_account_id=broker_account_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            executed_at=executed_at,
            notes=notes,
            source=source,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return row

    async def list_since(
        self,
        since: datetime,
        symbol: str | None = None,
        broker_account_id: uuid.UUID | None = None,
    ) -> list[ManualTrade]:
        q = select(ManualTrade).where(ManualTrade.executed_at >= since)
        if symbol:
            q = q.where(ManualTrade.symbol == symbol)
        if broker_account_id is not None:
            q = q.where(ManualTrade.broker_account_id == broker_account_id)
        q = q.order_by(ManualTrade.executed_at)
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def list_by_symbol(
        self, symbol: str, broker_account_id: uuid.UUID | None = None
    ) -> list[ManualTrade]:
        q = (
            select(ManualTrade)
            .where(ManualTrade.symbol == symbol)
            .order_by(ManualTrade.executed_at)
        )
        if broker_account_id is not None:
            q = q.where(ManualTrade.broker_account_id == broker_account_id)
        result = await self._s.execute(q)
        return list(result.scalars().all())


class TradingProfileSnapshotRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def latest(
        self,
        period_months: int | None = None,
        broker_account_id: uuid.UUID | None = None,
    ) -> TradingProfileSnapshot | None:
        q = select(TradingProfileSnapshot)
        if period_months is not None:
            q = q.where(TradingProfileSnapshot.period_months == period_months)
        if broker_account_id is not None:
            q = q.where(TradingProfileSnapshot.broker_account_id == broker_account_id)
        q = q.order_by(
            TradingProfileSnapshot.as_of_date.desc(),
            TradingProfileSnapshot.created_at.desc(),
        ).limit(1)
        result = await self._s.execute(q)
        return result.scalar_one_or_none()

    async def create(
        self, profile: Any, broker_account_id: uuid.UUID | None = None
    ) -> TradingProfileSnapshot:
        row = TradingProfileSnapshot(
            broker_account_id=broker_account_id,
            period_months=profile.period_months,
            as_of_date=profile.as_of_date,
            total_executions=profile.total_executions,
            total_symbols_traded=profile.total_symbols_traded,
            win_rate=profile.win_rate,
            avg_winner_pct=profile.avg_winner_pct,
            avg_loser_pct=profile.avg_loser_pct,
            profit_factor=profile.profit_factor,
            avg_holding_days=profile.avg_holding_days,
            disposition_effect_score=profile.disposition_effect_score,
            concentration_score=profile.concentration_score,
            recency_bias_score=profile.recency_bias_score,
            behavioral_flags_json=profile.behavioral_flags or [],
            per_symbol_stats_json=profile.per_symbol_stats or {},
            raw_metrics_json=profile.raw_metrics or {},
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return row


class BrokerAccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def get_by_id(self, account_id: uuid.UUID) -> BrokerAccount | None:
        result = await self._s.execute(
            select(BrokerAccount).where(BrokerAccount.id == account_id)
        )
        return result.scalar_one_or_none()

    async def list_active(
        self, user_id: uuid.UUID | None = None
    ) -> list[BrokerAccount]:
        q = select(BrokerAccount).where(BrokerAccount.is_active.is_(True))
        if user_id is not None:
            q = q.where(BrokerAccount.user_id == user_id)
        result = await self._s.execute(q)
        return list(result.scalars().all())

    async def get_active_default(
        self, user_id: uuid.UUID | None = None
    ) -> BrokerAccount | None:
        """Return first active account for this user (or global if user_id None)."""
        q = (
            select(BrokerAccount)
            .where(BrokerAccount.is_active.is_(True))
            .order_by(BrokerAccount.created_at)
            .limit(1)
        )
        if user_id is not None:
            q = q.where(BrokerAccount.user_id == user_id)
        result = await self._s.execute(q)
        return result.scalar_one_or_none()

    async def ensure_dev_default(self) -> BrokerAccount:
        """Return the default dev account, creating it if absent."""
        from core.config import get_settings

        existing = await self.get_active_default()
        if existing is not None:
            return existing

        cfg = get_settings()
        account = BrokerAccount(
            provider="IBKR",
            display_name="Dev Default (LOCAL_TWS)",
            connection_mode="LOCAL_TWS",
            host=cfg.ibkr_host,
            port=cfg.ibkr_port,
            client_id=cfg.ibkr_client_id,
            readonly=cfg.ibkr_readonly,
            is_active=True,
            metadata_json={"auto_created": True, "source": "ensure_dev_default"},
        )
        self._s.add(account)
        await self._s.flush()
        await self._s.refresh(account)
        return account

    async def create(
        self,
        provider: str,
        display_name: str,
        connection_mode: str,
        host: str | None,
        port: int | None,
        client_id: int,
        readonly: bool,
        is_active: bool = True,
        user_id: uuid.UUID | None = None,
        external_account_id: str | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> BrokerAccount:
        account = BrokerAccount(
            user_id=user_id,
            provider=provider,
            display_name=display_name,
            connection_mode=connection_mode,
            host=host,
            port=port,
            client_id=client_id,
            readonly=readonly,
            is_active=is_active,
            external_account_id=external_account_id,
            metadata_json=metadata_json or {},
        )
        self._s.add(account)
        await self._s.flush()
        await self._s.refresh(account)
        return account

    async def update(
        self,
        account_id: uuid.UUID,
        **fields: Any,
    ) -> BrokerAccount | None:
        allowed = {
            "display_name", "connection_mode", "host", "port",
            "client_id", "is_active", "metadata_json",
        }
        filtered = {k: v for k, v in fields.items() if k in allowed}
        if not filtered:
            return await self.get_by_id(account_id)
        filtered["updated_at"] = datetime.now(UTC)
        await self._s.execute(
            update(BrokerAccount)
            .where(BrokerAccount.id == account_id)
            .values(**filtered)
        )
        await self._s.flush()
        return await self.get_by_id(account_id)

    async def mark_sync_success(self, account_id: uuid.UUID) -> None:
        await self._s.execute(
            update(BrokerAccount)
            .where(BrokerAccount.id == account_id)
            .values(
                last_sync_at=datetime.now(UTC),
                last_sync_status="success",
                last_sync_error=None,
                updated_at=datetime.now(UTC),
            )
        )
        await self._s.flush()

    async def mark_sync_failure(self, account_id: uuid.UUID, error: str) -> None:
        await self._s.execute(
            update(BrokerAccount)
            .where(BrokerAccount.id == account_id)
            .values(
                last_sync_at=datetime.now(UTC),
                last_sync_status="failure",
                last_sync_error=error[:2000],
                updated_at=datetime.now(UTC),
            )
        )
        await self._s.flush()
