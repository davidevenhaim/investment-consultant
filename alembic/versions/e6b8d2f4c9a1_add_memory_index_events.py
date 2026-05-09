"""Add memory_index_events table — M6 ChromaDB audit trail.

Revision ID: e6b8d2f4c9a1
Revises: c3f5a8b2e1d7
Create Date: 2026-05-09
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6b8d2f4c9a1"
down_revision: Union[str, None] = "c3f5a8b2e1d7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "memory_index_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=True),
        sa.Column("collection_name", sa.String(100), nullable=False),
        sa.Column("chroma_document_id", sa.String(200), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_memory_index_events_entity",
        "memory_index_events",
        ["entity_type", "entity_id"],
    )
    op.create_index("ix_memory_index_events_symbol", "memory_index_events", ["symbol"])
    op.create_index("ix_memory_index_events_status", "memory_index_events", ["status"])
    op.create_index(
        "ix_memory_index_events_created_at", "memory_index_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_memory_index_events_created_at", table_name="memory_index_events")
    op.drop_index("ix_memory_index_events_status", table_name="memory_index_events")
    op.drop_index("ix_memory_index_events_symbol", table_name="memory_index_events")
    op.drop_index("ix_memory_index_events_entity", table_name="memory_index_events")
    op.drop_table("memory_index_events")
