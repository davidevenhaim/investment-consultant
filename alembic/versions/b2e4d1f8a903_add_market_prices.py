"""Add market_prices table — M4 real market data.

Revision ID: b2e4d1f8a903
Revises: a8f3b291c7e4
Create Date: 2026-05-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b2e4d1f8a903"
down_revision: Union[str, None] = "a8f3b291c7e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_prices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("price_date", sa.Date, nullable=False),
        sa.Column("open", sa.Numeric(15, 4), nullable=False),
        sa.Column("high", sa.Numeric(15, 4), nullable=False),
        sa.Column("low", sa.Numeric(15, 4), nullable=False),
        sa.Column("close", sa.Numeric(15, 4), nullable=False),
        sa.Column("adjusted_close", sa.Numeric(15, 4), nullable=True),
        sa.Column("volume", sa.BigInteger, nullable=True),
        sa.Column("provider", sa.String(50), nullable=False, server_default="yfinance"),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "symbol", "price_date", "provider", name="uq_market_price_symbol_date_provider"
        ),
    )
    op.create_index("ix_market_prices_symbol_date", "market_prices", ["symbol", "price_date"])
    op.create_index("ix_market_prices_symbol", "market_prices", ["symbol"])
    op.create_index("ix_market_prices_date", "market_prices", ["price_date"])


def downgrade() -> None:
    op.drop_index("ix_market_prices_date", table_name="market_prices")
    op.drop_index("ix_market_prices_symbol", table_name="market_prices")
    op.drop_index("ix_market_prices_symbol_date", table_name="market_prices")
    op.drop_table("market_prices")
