"""Add social_posts table — social sentiment ingestion (StockTwits + X).

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2026-08-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "j3k4l5m6n7o8"
down_revision: Union[str, None] = "i2j3k4l5m6n7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "social_posts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("provider_post_id", sa.String(200), nullable=False),
        sa.Column("author_handle", sa.String(200), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column(
            "posted_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "fetched_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "raw_json",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("sentiment_score", sa.Float, nullable=True),
        sa.Column("likes_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("reposts_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("replies_count", sa.Integer, nullable=True),
        sa.Column("is_duplicate", sa.Boolean, nullable=False, server_default="false"),
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
            "symbol",
            "provider",
            "provider_post_id",
            name="uq_social_symbol_provider_post",
        ),
    )
    op.create_index("ix_social_posts_symbol", "social_posts", ["symbol"])
    op.create_index("ix_social_posts_posted_at", "social_posts", ["posted_at"])
    op.create_index("ix_social_posts_provider", "social_posts", ["provider"])


def downgrade() -> None:
    op.drop_index("ix_social_posts_provider", table_name="social_posts")
    op.drop_index("ix_social_posts_posted_at", table_name="social_posts")
    op.drop_index("ix_social_posts_symbol", table_name="social_posts")
    op.drop_table("social_posts")
