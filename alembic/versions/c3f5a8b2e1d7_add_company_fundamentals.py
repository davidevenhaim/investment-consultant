"""Add company_fundamentals table — M5 real fundamentals data.

Revision ID: c3f5a8b2e1d7
Revises: b2e4d1f8a903
Create Date: 2026-05-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3f5a8b2e1d7"
down_revision: Union[str, None] = "b2e4d1f8a903"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_fundamentals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column("provider", sa.String(50), nullable=False, server_default="yfinance"),
        sa.Column("market_cap", sa.Numeric(20, 2), nullable=True),
        sa.Column("trailing_pe", sa.Numeric(10, 4), nullable=True),
        sa.Column("forward_pe", sa.Numeric(10, 4), nullable=True),
        sa.Column("price_to_book", sa.Numeric(10, 4), nullable=True),
        sa.Column("price_to_sales", sa.Numeric(10, 4), nullable=True),
        sa.Column("enterprise_to_revenue", sa.Numeric(10, 4), nullable=True),
        sa.Column("enterprise_to_ebitda", sa.Numeric(10, 4), nullable=True),
        sa.Column("revenue_growth", sa.Numeric(10, 6), nullable=True),
        sa.Column("earnings_growth", sa.Numeric(10, 6), nullable=True),
        sa.Column("profit_margins", sa.Numeric(10, 6), nullable=True),
        sa.Column("gross_margins", sa.Numeric(10, 6), nullable=True),
        sa.Column("operating_margins", sa.Numeric(10, 6), nullable=True),
        sa.Column("return_on_equity", sa.Numeric(10, 6), nullable=True),
        sa.Column("debt_to_equity", sa.Numeric(10, 4), nullable=True),
        sa.Column("current_ratio", sa.Numeric(10, 4), nullable=True),
        sa.Column("free_cashflow", sa.Numeric(20, 2), nullable=True),
        sa.Column("total_cash", sa.Numeric(20, 2), nullable=True),
        sa.Column("total_debt", sa.Numeric(20, 2), nullable=True),
        sa.Column(
            "raw_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
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
            "symbol", "as_of_date", "provider",
            name="uq_company_fundamentals_symbol_date_provider",
        ),
    )
    op.create_index(
        "ix_company_fundamentals_symbol_date", "company_fundamentals", ["symbol", "as_of_date"]
    )
    op.create_index("ix_company_fundamentals_symbol", "company_fundamentals", ["symbol"])
    op.create_index("ix_company_fundamentals_date", "company_fundamentals", ["as_of_date"])
    op.create_index("ix_company_fundamentals_provider", "company_fundamentals", ["provider"])


def downgrade() -> None:
    op.drop_index("ix_company_fundamentals_provider", table_name="company_fundamentals")
    op.drop_index("ix_company_fundamentals_date", table_name="company_fundamentals")
    op.drop_index("ix_company_fundamentals_symbol", table_name="company_fundamentals")
    op.drop_index("ix_company_fundamentals_symbol_date", table_name="company_fundamentals")
    op.drop_table("company_fundamentals")
