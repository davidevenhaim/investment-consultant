"""Add portfolio tables — M9 portfolio context.

Revision ID: b3c4d5e6f7a8
Revises: a1b2c3d4e5f6
Create Date: 2026-05-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "portfolio_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("account_type", sa.String(50), nullable=False, server_default="MANUAL"),
        sa.Column("base_currency", sa.String(10), nullable=False, server_default="USD"),
        sa.Column("cash_balance", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
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
    )

    op.create_table(
        "portfolio_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("portfolio_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 6), nullable=False),
        sa.Column("average_cost", sa.Numeric(18, 4), nullable=True),
        sa.Column("current_price", sa.Numeric(18, 4), nullable=True),
        sa.Column("market_value", sa.Numeric(18, 4), nullable=True),
        sa.Column("cost_basis", sa.Numeric(18, 4), nullable=True),
        sa.Column("unrealized_pnl", sa.Numeric(18, 4), nullable=True),
        sa.Column("unrealized_pnl_pct", sa.Float, nullable=True),
        sa.Column("weight", sa.Float, nullable=True),
        sa.Column(
            "as_of_time",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
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
        sa.UniqueConstraint("account_id", "symbol", name="uq_position_account_symbol"),
    )
    op.create_index("ix_portfolio_positions_account_id", "portfolio_positions", ["account_id"])
    op.create_index("ix_portfolio_positions_symbol", "portfolio_positions", ["symbol"])
    op.create_index(
        "ix_portfolio_positions_account_weight", "portfolio_positions", ["account_id", "weight"]
    )

    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "account_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("portfolio_accounts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("total_market_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("cash_balance", sa.Numeric(18, 4), nullable=False, server_default="0"),
        sa.Column("total_equity", sa.Numeric(18, 4), nullable=False),
        sa.Column("number_of_positions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("max_position_weight", sa.Float, nullable=True),
        sa.Column(
            "top_positions_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "sector_exposure_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "risk_metrics_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "as_of_time",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_portfolio_snapshots_account_id", "portfolio_snapshots", ["account_id"])
    op.create_index("ix_portfolio_snapshots_as_of_time", "portfolio_snapshots", ["as_of_time"])
    op.create_index(
        "ix_portfolio_snapshots_account_time",
        "portfolio_snapshots",
        ["account_id", "as_of_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_portfolio_snapshots_account_time", table_name="portfolio_snapshots")
    op.drop_index("ix_portfolio_snapshots_as_of_time", table_name="portfolio_snapshots")
    op.drop_index("ix_portfolio_snapshots_account_id", table_name="portfolio_snapshots")
    op.drop_table("portfolio_snapshots")

    op.drop_index("ix_portfolio_positions_account_weight", table_name="portfolio_positions")
    op.drop_index("ix_portfolio_positions_symbol", table_name="portfolio_positions")
    op.drop_index("ix_portfolio_positions_account_id", table_name="portfolio_positions")
    op.drop_table("portfolio_positions")

    op.drop_table("portfolio_accounts")
