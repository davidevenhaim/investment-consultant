"""Scope IBKR execution dedupe by broker account.

Revision ID: b1c2d3e4f5a6
Revises: a9b1c2d3e4f5
Create Date: 2026-05-12
"""

from typing import Sequence, Union

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a9b1c2d3e4f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_ibkr_exec_id", "ibkr_executions", type_="unique")
    op.create_unique_constraint(
        "uq_ibkr_executions_broker_exec_id",
        "ibkr_executions",
        ["broker_account_id", "exec_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_ibkr_executions_broker_exec_id",
        "ibkr_executions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_ibkr_exec_id",
        "ibkr_executions",
        ["exec_id"],
    )
