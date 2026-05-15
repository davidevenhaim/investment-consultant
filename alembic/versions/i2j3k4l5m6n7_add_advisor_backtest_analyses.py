"""Add advisor_backtest_analyses table for local Ollama analysis results.

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5m6
Create Date: 2026-05-15
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "i2j3k4l5m6n7"
down_revision: Union[str, None] = "h1i2j3k4l5m6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "advisor_backtest_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "advisor_backtest_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("advisor_backtest_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "provider",
            sa.String(50),
            nullable=False,
            server_default=sa.text("'ollama'"),
        ),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column(
            "prompt_version",
            sa.String(100),
            nullable=False,
            server_default=sa.text("'ollama_backtest_analyst_v1'"),
        ),
        # COMPLETED | FAILED
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column(
            "analysis_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "prompt_input_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_message", sa.Text, nullable=True),
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
    op.create_index("ix_aba_user_id", "advisor_backtest_analyses", ["user_id"])
    op.create_index(
        "ix_aba_run_id", "advisor_backtest_analyses", ["advisor_backtest_run_id"]
    )
    op.create_index("ix_aba_status", "advisor_backtest_analyses", ["status"])
    op.create_index("ix_aba_created_at", "advisor_backtest_analyses", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_aba_created_at", table_name="advisor_backtest_analyses")
    op.drop_index("ix_aba_status", table_name="advisor_backtest_analyses")
    op.drop_index("ix_aba_run_id", table_name="advisor_backtest_analyses")
    op.drop_index("ix_aba_user_id", table_name="advisor_backtest_analyses")
    op.drop_table("advisor_backtest_analyses")
