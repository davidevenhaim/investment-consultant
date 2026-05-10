"""Add symbol_trading_stats_json to personalized_recommendations.

Revision ID: f7a9c3e5b1d2
Revises: e6b8d2f4c9a1
Create Date: 2026-05-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "f7a9c3e5b1d2"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "personalized_recommendations",
        sa.Column(
            "symbol_trading_stats_json",
            JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("personalized_recommendations", "symbol_trading_stats_json")
