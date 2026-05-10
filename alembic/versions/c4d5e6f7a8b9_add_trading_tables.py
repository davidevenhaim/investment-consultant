"""Add trading history tables — M9.5 IBKR + trading profile.

Revision ID: c4d5e6f7a8b9
Revises: b3c4d5e6f7a8
Create Date: 2026-05-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, None] = "b3c4d5e6f7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ibkr_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id_ibkr", sa.String(50), nullable=False),
        sa.Column("exec_id", sa.String(255), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("exchange", sa.String(50), nullable=True),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=False),
        sa.Column("commission", sa.Numeric(18, 4), nullable=True),
        sa.Column("currency", sa.String(10), nullable=False, server_default="USD"),
        sa.Column("executed_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("order_ref", sa.String(255), nullable=True),
        sa.Column(
            "raw_json", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("exec_id", name="uq_ibkr_exec_id"),
    )
    op.create_index("ix_ibkr_executions_symbol", "ibkr_executions", ["symbol"])
    op.create_index("ix_ibkr_executions_executed_at", "ibkr_executions", ["executed_at"])
    op.create_index("ix_ibkr_executions_symbol_date", "ibkr_executions", ["symbol", "executed_at"])
    op.create_index("ix_ibkr_executions_account", "ibkr_executions", ["account_id_ibkr"])
    op.create_index("ix_ibkr_executions_side", "ibkr_executions", ["side"])

    op.create_table(
        "manual_trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("side", sa.String(10), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=False),
        sa.Column("executed_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("source", sa.String(50), nullable=False, server_default="manual"),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_manual_trades_symbol", "manual_trades", ["symbol"])
    op.create_index("ix_manual_trades_executed_at", "manual_trades", ["executed_at"])
    op.create_index("ix_manual_trades_symbol_date", "manual_trades", ["symbol", "executed_at"])

    op.create_table(
        "trading_profile_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period_months", sa.Integer, nullable=False, server_default="12"),
        sa.Column("as_of_date", sa.Date, nullable=False),
        sa.Column("total_executions", sa.Integer, nullable=False, server_default="0"),
        sa.Column("total_symbols_traded", sa.Integer, nullable=False, server_default="0"),
        sa.Column("win_rate", sa.Numeric(5, 4), nullable=True),
        sa.Column("avg_winner_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("avg_loser_pct", sa.Numeric(8, 4), nullable=True),
        sa.Column("profit_factor", sa.Numeric(8, 4), nullable=True),
        sa.Column("avg_holding_days", sa.Numeric(8, 2), nullable=True),
        sa.Column("disposition_effect_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("concentration_score", sa.Numeric(5, 4), nullable=True),
        sa.Column("recency_bias_score", sa.Numeric(5, 4), nullable=True),
        sa.Column(
            "behavioral_flags_json", postgresql.JSONB, nullable=False,
            server_default=sa.text("'[]'::jsonb")
        ),
        sa.Column(
            "per_symbol_stats_json", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "sector_stats_json", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "raw_metrics_json", postgresql.JSONB, nullable=False,
            server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at", postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_trading_profile_as_of_date", "trading_profile_snapshots", ["as_of_date"])
    op.create_index("ix_trading_profile_period", "trading_profile_snapshots", ["period_months"])


def downgrade() -> None:
    op.drop_index("ix_trading_profile_period", table_name="trading_profile_snapshots")
    op.drop_index("ix_trading_profile_as_of_date", table_name="trading_profile_snapshots")
    op.drop_table("trading_profile_snapshots")

    op.drop_index("ix_manual_trades_symbol_date", table_name="manual_trades")
    op.drop_index("ix_manual_trades_executed_at", table_name="manual_trades")
    op.drop_index("ix_manual_trades_symbol", table_name="manual_trades")
    op.drop_table("manual_trades")

    op.drop_index("ix_ibkr_executions_side", table_name="ibkr_executions")
    op.drop_index("ix_ibkr_executions_account", table_name="ibkr_executions")
    op.drop_index("ix_ibkr_executions_symbol_date", table_name="ibkr_executions")
    op.drop_index("ix_ibkr_executions_executed_at", table_name="ibkr_executions")
    op.drop_index("ix_ibkr_executions_symbol", table_name="ibkr_executions")
    op.drop_table("ibkr_executions")
