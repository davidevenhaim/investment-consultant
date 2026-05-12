"""Add nullable user ownership roots for M10.1.

Revision ID: a9b1c2d3e4f5
Revises: f7a9c3e5b1d2
Create Date: 2026-05-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a9b1c2d3e4f5"
down_revision: Union[str, None] = "f7a9c3e5b1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "investor_profiles",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_investor_profiles_user_id", "investor_profiles", ["user_id"])

    op.add_column(
        "portfolio_accounts",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_portfolio_accounts_user_id", "portfolio_accounts", ["user_id"])

    op.add_column(
        "watchlist_symbols",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_watchlist_symbols_user_id", "watchlist_symbols", ["user_id"])
    op.drop_constraint("uq_watchlist_symbol", "watchlist_symbols", type_="unique")
    op.create_unique_constraint(
        "uq_watchlist_user_symbol",
        "watchlist_symbols",
        ["user_id", "symbol"],
    )

    op.add_column(
        "research_runs",
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index("ix_research_runs_user_id", "research_runs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_research_runs_user_id", table_name="research_runs")
    op.drop_column("research_runs", "user_id")

    op.drop_constraint("uq_watchlist_user_symbol", "watchlist_symbols", type_="unique")
    op.create_unique_constraint("uq_watchlist_symbol", "watchlist_symbols", ["symbol"])
    op.drop_index("ix_watchlist_symbols_user_id", table_name="watchlist_symbols")
    op.drop_column("watchlist_symbols", "user_id")

    op.drop_index("ix_portfolio_accounts_user_id", table_name="portfolio_accounts")
    op.drop_column("portfolio_accounts", "user_id")

    op.drop_index("ix_investor_profiles_user_id", table_name="investor_profiles")
    op.drop_column("investor_profiles", "user_id")
