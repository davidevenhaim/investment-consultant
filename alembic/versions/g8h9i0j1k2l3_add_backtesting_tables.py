"""Add recommendation_outcomes and learning_events tables for M11.

Revision ID: g8h9i0j1k2l3
Revises: b1c2d3e4f5a6
Create Date: 2026-05-13
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "g8h9i0j1k2l3"
down_revision: Union[str, None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recommendation_outcomes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recommendation_type", sa.String(30), nullable=False),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("research_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("score", sa.Integer(), nullable=True),
        sa.Column("price_at_recommendation", sa.Numeric(15, 4), nullable=True),
        sa.Column("measured_from", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("measured_to", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column(
            "benchmark_symbol", sa.String(20), nullable=True, server_default="SPY"
        ),
        sa.Column("start_price", sa.Numeric(15, 4), nullable=True),
        sa.Column("end_price", sa.Numeric(15, 4), nullable=True),
        sa.Column("benchmark_start_price", sa.Numeric(15, 4), nullable=True),
        sa.Column("benchmark_end_price", sa.Numeric(15, 4), nullable=True),
        sa.Column("forward_return_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("benchmark_return_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("relative_return_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("max_drawdown_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("max_runup_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("outcome_status", sa.String(30), nullable=False),
        sa.Column("outcome_label", sa.String(30), nullable=True),
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
            "recommendation_type",
            "recommendation_id",
            "horizon_days",
            "benchmark_symbol",
            name="uq_outcome_rec_horizon_benchmark",
        ),
    )
    op.create_index("ix_outcome_user_id", "recommendation_outcomes", ["user_id"])
    op.create_index("ix_outcome_symbol", "recommendation_outcomes", ["symbol"])
    op.create_index(
        "ix_outcome_research_run_id", "recommendation_outcomes", ["research_run_id"]
    )
    op.create_index(
        "ix_outcome_rec_type_id",
        "recommendation_outcomes",
        ["recommendation_type", "recommendation_id"],
    )
    op.create_index("ix_outcome_measured_to", "recommendation_outcomes", ["measured_to"])
    op.create_index("ix_outcome_status", "recommendation_outcomes", ["outcome_status"])

    op.create_table(
        "learning_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "recommendation_outcome_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recommendation_outcomes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("research_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "suspected_causes_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "evidence_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "suggested_adjustments_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.String(30), nullable=False, server_default="OPEN"),
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
    op.create_index("ix_learning_user_id", "learning_events", ["user_id"])
    op.create_index("ix_learning_symbol", "learning_events", ["symbol"])
    op.create_index("ix_learning_event_type", "learning_events", ["event_type"])
    op.create_index("ix_learning_status", "learning_events", ["status"])
    op.create_index("ix_learning_research_run_id", "learning_events", ["research_run_id"])


def downgrade() -> None:
    op.drop_index("ix_learning_research_run_id", table_name="learning_events")
    op.drop_index("ix_learning_status", table_name="learning_events")
    op.drop_index("ix_learning_event_type", table_name="learning_events")
    op.drop_index("ix_learning_symbol", table_name="learning_events")
    op.drop_index("ix_learning_user_id", table_name="learning_events")
    op.drop_table("learning_events")

    op.drop_index("ix_outcome_status", table_name="recommendation_outcomes")
    op.drop_index("ix_outcome_measured_to", table_name="recommendation_outcomes")
    op.drop_index("ix_outcome_rec_type_id", table_name="recommendation_outcomes")
    op.drop_index("ix_outcome_research_run_id", table_name="recommendation_outcomes")
    op.drop_index("ix_outcome_symbol", table_name="recommendation_outcomes")
    op.drop_index("ix_outcome_user_id", table_name="recommendation_outcomes")
    op.drop_table("recommendation_outcomes")
