"""DB read/write for market_prices table."""

import datetime as dt

from db.models import MarketPrice
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from market_data.schemas import MarketPriceBar


class MarketPriceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._s = session

    async def upsert_bars(self, bars: list[MarketPriceBar]) -> int:
        """Upsert price bars. Returns number of rows affected."""
        if not bars:
            return 0
        rows = [
            {
                "symbol": b.symbol,
                "price_date": b.price_date,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "adjusted_close": b.adjusted_close,
                "volume": b.volume,
                "provider": b.provider,
            }
            for b in bars
        ]
        stmt = pg_insert(MarketPrice).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_market_price_symbol_date_provider",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "adjusted_close": stmt.excluded.adjusted_close,
                "volume": stmt.excluded.volume,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        await self._s.execute(stmt)
        await self._s.flush()
        return len(bars)

    async def get_bars(
        self,
        symbol: str,
        provider: str = "yfinance",
        start_date: dt.date | None = None,
        end_date: dt.date | None = None,
    ) -> list[MarketPriceBar]:
        """Return bars ordered ascending."""
        q = select(MarketPrice).where(
            MarketPrice.symbol == symbol.upper(),
            MarketPrice.provider == provider,
        )
        if start_date:
            q = q.where(MarketPrice.price_date >= start_date)
        if end_date:
            q = q.where(MarketPrice.price_date <= end_date)
        q = q.order_by(MarketPrice.price_date.asc())
        result = await self._s.execute(q)
        rows = result.scalars().all()
        return [
            MarketPriceBar(
                symbol=r.symbol,
                price_date=r.price_date,
                open=float(r.open),
                high=float(r.high),
                low=float(r.low),
                close=float(r.close),
                adjusted_close=float(r.adjusted_close) if r.adjusted_close is not None else None,
                volume=r.volume,
                provider=r.provider,
            )
            for r in rows
        ]

    async def count_bars(self, symbol: str, provider: str = "yfinance") -> int:
        from sqlalchemy import func as sqlfunc

        result = await self._s.execute(
            select(sqlfunc.count()).where(
                MarketPrice.symbol == symbol.upper(),
                MarketPrice.provider == provider,
            )
        )
        return int(result.scalar() or 0)

    async def latest_date(self, symbol: str, provider: str = "yfinance") -> dt.date | None:
        from sqlalchemy import func as sqlfunc

        result = await self._s.execute(
            select(sqlfunc.max(MarketPrice.price_date)).where(
                MarketPrice.symbol == symbol.upper(),
                MarketPrice.provider == provider,
            )
        )
        return result.scalar()
