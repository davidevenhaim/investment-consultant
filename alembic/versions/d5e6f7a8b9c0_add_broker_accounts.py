"""Add broker_accounts table and broker_account_id FK columns — M9.6.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-05-10
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "broker_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(50), nullable=False, server_default="IBKR"),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("external_account_id", sa.String(100), nullable=True),
        sa.Column(
            "connection_mode", sa.String(50), nullable=False, server_default="LOCAL_TWS"
        ),
        sa.Column("host", sa.String(255), nullable=True),
        sa.Column("port", sa.Integer, nullable=True),
        sa.Column("client_id", sa.Integer, nullable=False, server_default="1"),
        sa.Column("readonly", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "last_sync_at", postgresql.TIMESTAMP(timezone=True), nullable=True
        ),
        sa.Column("last_sync_status", sa.String(50), nullable=True),
        sa.Column("last_sync_error", sa.Text, nullable=True),
        sa.Column(
            "metadata_json",
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
    )
    op.create_index("ix_broker_accounts_user_id", "broker_accounts", ["user_id"])
    op.create_index("ix_broker_accounts_provider", "broker_accounts", ["provider"])
    op.create_index("ix_broker_accounts_active", "broker_accounts", ["is_active"])

    # Add broker_account_id FK to ibkr_executions
    op.add_column(
        "ibkr_executions",
        sa.Column("broker_account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_ibkr_executions_broker_account",
        "ibkr_executions",
        "broker_accounts",
        ["broker_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_ibkr_executions_broker_account_id",
        "ibkr_executions",
        ["broker_account_id"],
    )

    # Add broker_account_id FK to manual_trades
    op.add_column(
        "manual_trades",
        sa.Column("broker_account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_manual_trades_broker_account",
        "manual_trades",
        "broker_accounts",
        ["broker_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_manual_trades_broker_account_id",
        "manual_trades",
        ["broker_account_id"],
    )

    # Add broker_account_id FK to trading_profile_snapshots
    op.add_column(
        "trading_profile_snapshots",
        sa.Column("broker_account_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_trading_profile_snapshots_broker_account",
        "trading_profile_snapshots",
        "broker_accounts",
        ["broker_account_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_trading_profile_broker_account_id",
        "trading_profile_snapshots",
        ["broker_account_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_trading_profile_broker_account_id", table_name="trading_profile_snapshots")
    op.drop_constraint(
        "fk_trading_profile_snapshots_broker_account",
        "trading_profile_snapshots",
        type_="foreignkey",
    )
    op.drop_column("trading_profile_snapshots", "broker_account_id")

    op.drop_index("ix_manual_trades_broker_account_id", table_name="manual_trades")
    op.drop_constraint(
        "fk_manual_trades_broker_account", "manual_trades", type_="foreignkey"
    )
    op.drop_column("manual_trades", "broker_account_id")

    op.drop_index("ix_ibkr_executions_broker_account_id", table_name="ibkr_executions")
    op.drop_constraint(
        "fk_ibkr_executions_broker_account", "ibkr_executions", type_="foreignkey"
    )
    op.drop_column("ibkr_executions", "broker_account_id")

    op.drop_index("ix_broker_accounts_active", table_name="broker_accounts")
    op.drop_index("ix_broker_accounts_provider", table_name="broker_accounts")
    op.drop_index("ix_broker_accounts_user_id", table_name="broker_accounts")
    op.drop_table("broker_accounts")
