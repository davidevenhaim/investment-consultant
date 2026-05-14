"""Add advisor_backtest_runs, advisor_backtest_trades, advisor_backtest_equity_points.

Revision ID: h1i2j3k4l5m6
Revises: g8h9i0j1k2l3
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "h1i2j3k4l5m6"
down_revision: Union[str, None] = "g8h9i0j1k2l3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "advisor_backtest_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("initial_cash", sa.Numeric(18, 4), nullable=False),
        sa.Column("final_equity", sa.Numeric(18, 4), nullable=True),
        sa.Column("cash_final", sa.Numeric(18, 4), nullable=True),
        sa.Column("total_return_pct", sa.Numeric(18, 8), nullable=True),
        sa.Column(
            "benchmark_symbol", sa.String(20), nullable=True, server_default="SPY"
        ),
        sa.Column("benchmark_return_pct", sa.Numeric(18, 8), nullable=True),
        sa.Column("relative_return_pct", sa.Numeric(18, 8), nullable=True),
        sa.Column("max_drawdown_pct", sa.Numeric(18, 8), nullable=True),
        sa.Column("total_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("winning_trades", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("losing_trades", sa.Integer(), nullable=False, server_default="0"),
        # COMPLETED | INSUFFICIENT_DATA | ERROR
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "assumptions_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "summary_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ab_run_user_id", "advisor_backtest_runs", ["user_id"])
    op.create_index(
        "ix_ab_run_dates", "advisor_backtest_runs", ["start_date", "end_date"]
    )
    op.create_index("ix_ab_run_status", "advisor_backtest_runs", ["status"])
    op.create_index("ix_ab_run_created_at", "advisor_backtest_runs", ["created_at"])

    op.create_table(
        "advisor_backtest_trades",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "backtest_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("advisor_backtest_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("research_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(30), nullable=False),
        # BUY | SELL | REDUCE | SKIP
        sa.Column("trade_type", sa.String(20), nullable=False),
        sa.Column("trade_date", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(18, 4), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=True),
        sa.Column("cash_delta", sa.Numeric(18, 4), nullable=True),
        sa.Column("position_before", sa.Numeric(18, 8), nullable=True),
        sa.Column("position_after", sa.Numeric(18, 8), nullable=True),
        sa.Column("reason", sa.String(255), nullable=True),
        sa.Column(
            "raw_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ab_trade_run_id", "advisor_backtest_trades", ["backtest_run_id"])
    op.create_index("ix_ab_trade_user_id", "advisor_backtest_trades", ["user_id"])
    op.create_index("ix_ab_trade_symbol", "advisor_backtest_trades", ["symbol"])
    op.create_index("ix_ab_trade_date", "advisor_backtest_trades", ["trade_date"])

    op.create_table(
        "advisor_backtest_equity_points",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "backtest_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("advisor_backtest_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("equity", sa.Numeric(18, 4), nullable=False),
        sa.Column("cash", sa.Numeric(18, 4), nullable=False),
        sa.Column("positions_value", sa.Numeric(18, 4), nullable=False),
        sa.Column("drawdown_pct", sa.Numeric(18, 8), nullable=True),
        sa.Column("benchmark_value", sa.Numeric(18, 4), nullable=True),
        sa.Column(
            "raw_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "backtest_run_id", "date", name="uq_ab_equity_run_date"
        ),
    )
    op.create_index(
        "ix_ab_equity_run_id", "advisor_backtest_equity_points", ["backtest_run_id"]
    )
    op.create_index("ix_ab_equity_date", "advisor_backtest_equity_points", ["date"])


def downgrade() -> None:
    op.drop_index("ix_ab_equity_date", table_name="advisor_backtest_equity_points")
    op.drop_index("ix_ab_equity_run_id", table_name="advisor_backtest_equity_points")
    op.drop_table("advisor_backtest_equity_points")

    op.drop_index("ix_ab_trade_date", table_name="advisor_backtest_trades")
    op.drop_index("ix_ab_trade_symbol", table_name="advisor_backtest_trades")
    op.drop_index("ix_ab_trade_user_id", table_name="advisor_backtest_trades")
    op.drop_index("ix_ab_trade_run_id", table_name="advisor_backtest_trades")
    op.drop_table("advisor_backtest_trades")

    op.drop_index("ix_ab_run_created_at", table_name="advisor_backtest_runs")
    op.drop_index("ix_ab_run_status", table_name="advisor_backtest_runs")
    op.drop_index("ix_ab_run_dates", table_name="advisor_backtest_runs")
    op.drop_index("ix_ab_run_user_id", table_name="advisor_backtest_runs")
    op.drop_table("advisor_backtest_runs")
