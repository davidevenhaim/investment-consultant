"""Initial schema — all M2 tables.

Revision ID: a8f3b291c7e4
Revises:
Create Date: 2026-05-07
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a8f3b291c7e4"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── strategy_versions ────────────────────────────────────────────────────
    op.create_table(
        "strategy_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column(
            "scoring_config_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "risk_policy_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("version", name="uq_strategy_versions_version"),
    )

    # ── prompt_versions ──────────────────────────────────────────────────────
    op.create_table(
        "prompt_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("version", sa.String(50), nullable=False),
        sa.Column("prompt_text", sa.Text, nullable=False),
        sa.Column(
            "output_schema_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("name", "version", name="uq_prompt_name_version"),
    )

    # ── watchlist_symbols ────────────────────────────────────────────────────
    op.create_table(
        "watchlist_symbols",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("company_name", sa.String(200), nullable=True),
        sa.Column("exchange", sa.String(20), nullable=True),
        sa.Column(
            "asset_type", sa.String(30), nullable=False, server_default=sa.text("'EQUITY'")
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("symbol", name="uq_watchlist_symbol"),
    )

    # ── investor_profiles ────────────────────────────────────────────────────
    op.create_table(
        "investor_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, server_default=sa.text("'default'")),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default=sa.text("'MEDIUM'")),
        sa.Column(
            "max_single_stock_weight", sa.Float(), nullable=False, server_default=sa.text("0.15")
        ),
        sa.Column(
            "max_new_position_weight", sa.Float(), nullable=False, server_default=sa.text("0.05")
        ),
        sa.Column(
            "max_drawdown_tolerance", sa.Float(), nullable=False, server_default=sa.text("0.25")
        ),
        sa.Column(
            "min_confidence_to_buy", sa.Float(), nullable=False, server_default=sa.text("0.65")
        ),
        sa.Column("allow_margin", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("allow_options", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("allow_shorting", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "investment_horizon",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'3-12_MONTHS'"),
        ),
        sa.Column(
            "extra_config_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )

    # ── research_runs ────────────────────────────────────────────────────────
    op.create_table(
        "research_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'CREATED'")),
        sa.Column(
            "strategy_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("strategy_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "prompt_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_research_runs_status", "research_runs", ["status"])
    op.create_index("ix_research_runs_run_type", "research_runs", ["run_type"])
    op.create_index("ix_research_runs_created_at", "research_runs", ["created_at"])

    # ── research_run_tickers ─────────────────────────────────────────────────
    op.create_table(
        "research_run_tickers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default=sa.text("'CREATED'")),
        sa.Column("started_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("finished_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.UniqueConstraint("research_run_id", "symbol", name="uq_run_ticker_symbol"),
    )
    op.create_index("ix_run_tickers_run_id", "research_run_tickers", ["research_run_id"])
    op.create_index("ix_run_tickers_symbol", "research_run_tickers", ["symbol"])
    op.create_index("ix_run_tickers_status", "research_run_tickers", ["status"])

    # ── neutral_recommendations ──────────────────────────────────────────────
    op.create_table(
        "neutral_recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "research_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "research_run_ticker_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("research_run_tickers.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("time_horizon", sa.String(50), nullable=True),
        sa.Column(
            "score_breakdown_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "what_changed_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "main_reasons_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "main_risks_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "missing_details_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("final_reason", sa.Text, nullable=False),
        sa.Column(
            "strategy_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("strategy_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "prompt_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prompt_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("as_of_time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("price_at_recommendation", sa.Numeric(15, 4), nullable=True),
        sa.Column("data_quality_score", sa.Float(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.CheckConstraint("score >= 0 AND score <= 100", name="chk_neutral_rec_score"),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0", name="chk_neutral_rec_confidence"
        ),
        sa.CheckConstraint(
            "data_quality_score IS NULL OR"
            " (data_quality_score >= 0.0 AND data_quality_score <= 1.0)",
            name="chk_neutral_rec_dq",
        ),
    )
    op.create_index("ix_neutral_rec_symbol", "neutral_recommendations", ["symbol"])
    op.create_index("ix_neutral_rec_action", "neutral_recommendations", ["action"])
    op.create_index("ix_neutral_rec_as_of_time", "neutral_recommendations", ["as_of_time"])
    op.create_index("ix_neutral_rec_run_id", "neutral_recommendations", ["research_run_id"])

    # ── personalized_recommendations ─────────────────────────────────────────
    op.create_table(
        "personalized_recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "neutral_recommendation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("neutral_recommendations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "investor_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("investor_profiles.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("portfolio_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("personal_action", sa.String(30), nullable=False),
        sa.Column(
            "position_sizing_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "policy_checks_json",
            postgresql.JSONB(),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("current_position_weight", sa.Float(), nullable=True),
        sa.Column("max_allowed_weight", sa.Float(), nullable=True),
        sa.Column("personal_reason", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_personal_rec_symbol", "personalized_recommendations", ["symbol"])
    op.create_index(
        "ix_personal_rec_action", "personalized_recommendations", ["personal_action"]
    )

    # ── recommendation_evidence ──────────────────────────────────────────────
    op.create_table(
        "recommendation_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("recommendation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation_type", sa.String(30), nullable=False),
        sa.Column("evidence_type", sa.String(30), nullable=False),
        sa.Column("source", sa.String(200), nullable=True),
        sa.Column("source_id", sa.String(200), nullable=True),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("published_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "payload_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_evidence_rec_id", "recommendation_evidence", ["recommendation_id"])
    op.create_index(
        "ix_evidence_rec_type", "recommendation_evidence", ["recommendation_type"]
    )

    # ── job_events ───────────────────────────────────────────────────────────
    op.create_table(
        "job_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column(
            "payload_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_job_events_entity", "job_events", ["entity_type", "entity_id"])
    op.create_index("ix_job_events_event_type", "job_events", ["event_type"])
    op.create_index("ix_job_events_correlation_id", "job_events", ["correlation_id"])
    op.create_index("ix_job_events_created_at", "job_events", ["created_at"])

    # ── audit_logs ───────────────────────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(100), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor", sa.String(100), nullable=False, server_default=sa.text("'system'")),
        sa.Column(
            "payload_json",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("correlation_id", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
    )
    op.create_index("ix_audit_logs_entity", "audit_logs", ["entity_type", "entity_id"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_actor", "audit_logs", ["actor"])
    op.create_index("ix_audit_logs_correlation_id", "audit_logs", ["correlation_id"])
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("job_events")
    op.drop_table("recommendation_evidence")
    op.drop_table("personalized_recommendations")
    op.drop_table("neutral_recommendations")
    op.drop_table("research_run_tickers")
    op.drop_table("research_runs")
    op.drop_table("investor_profiles")
    op.drop_table("watchlist_symbols")
    op.drop_table("prompt_versions")
    op.drop_table("strategy_versions")
