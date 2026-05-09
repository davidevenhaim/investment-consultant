"""DB read/write for company_fundamentals table."""
import datetime as dt
from typing import Any

from db.models import CompanyFundamentals
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from fundamentals.schemas import CompanyFundamentalsSnapshot


class CompanyFundamentalsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert(self, snapshot: CompanyFundamentalsSnapshot) -> None:
        row: dict[str, Any] = {
            "symbol": snapshot.symbol,
            "as_of_date": snapshot.as_of_date,
            "provider": snapshot.provider,
            "market_cap": snapshot.market_cap,
            "trailing_pe": snapshot.trailing_pe,
            "forward_pe": snapshot.forward_pe,
            "price_to_book": snapshot.price_to_book,
            "price_to_sales": snapshot.price_to_sales,
            "enterprise_to_revenue": snapshot.enterprise_to_revenue,
            "enterprise_to_ebitda": snapshot.enterprise_to_ebitda,
            "revenue_growth": snapshot.revenue_growth,
            "earnings_growth": snapshot.earnings_growth,
            "profit_margins": snapshot.profit_margins,
            "gross_margins": snapshot.gross_margins,
            "operating_margins": snapshot.operating_margins,
            "return_on_equity": snapshot.return_on_equity,
            "debt_to_equity": snapshot.debt_to_equity,
            "current_ratio": snapshot.current_ratio,
            "free_cashflow": snapshot.free_cashflow,
            "total_cash": snapshot.total_cash,
            "total_debt": snapshot.total_debt,
            "raw_json": snapshot.raw_json,
        }
        stmt = pg_insert(CompanyFundamentals).values([row])
        _skip = {"symbol", "as_of_date", "provider"}
        stmt = stmt.on_conflict_do_update(
            constraint="uq_company_fundamentals_symbol_date_provider",
            set_={k: stmt.excluded[k] for k in row if k not in _skip},
        )
        await self._s.execute(stmt)
        await self._s.flush()

    async def get_latest(
        self, symbol: str, provider: str = "yfinance"
    ) -> CompanyFundamentalsSnapshot | None:
        result = await self._s.execute(
            select(CompanyFundamentals)
            .where(
                CompanyFundamentals.symbol == symbol.upper(),
                CompanyFundamentals.provider == provider,
            )
            .order_by(CompanyFundamentals.as_of_date.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return _row_to_snapshot(row)

    async def get_latest_date(
        self, symbol: str, provider: str = "yfinance"
    ) -> dt.date | None:
        from sqlalchemy import func as sqlfunc
        result = await self._s.execute(
            select(sqlfunc.max(CompanyFundamentals.as_of_date)).where(
                CompanyFundamentals.symbol == symbol.upper(),
                CompanyFundamentals.provider == provider,
            )
        )
        return result.scalar()


def _row_to_snapshot(row: CompanyFundamentals) -> CompanyFundamentalsSnapshot:
    return CompanyFundamentalsSnapshot(
        symbol=row.symbol,
        as_of_date=row.as_of_date,
        provider=row.provider,
        market_cap=_f(row.market_cap),
        trailing_pe=_f(row.trailing_pe),
        forward_pe=_f(row.forward_pe),
        price_to_book=_f(row.price_to_book),
        price_to_sales=_f(row.price_to_sales),
        enterprise_to_revenue=_f(row.enterprise_to_revenue),
        enterprise_to_ebitda=_f(row.enterprise_to_ebitda),
        revenue_growth=_f(row.revenue_growth),
        earnings_growth=_f(row.earnings_growth),
        profit_margins=_f(row.profit_margins),
        gross_margins=_f(row.gross_margins),
        operating_margins=_f(row.operating_margins),
        return_on_equity=_f(row.return_on_equity),
        debt_to_equity=_f(row.debt_to_equity),
        current_ratio=_f(row.current_ratio),
        free_cashflow=_f(row.free_cashflow),
        total_cash=_f(row.total_cash),
        total_debt=_f(row.total_debt),
        raw_json=row.raw_json or {},
    )


def _f(val: Any) -> float | None:
    return float(val) if val is not None else None
