"""Baseline schema for Proteus-Scraper.

Revision ID: 20250308_0001
Revises:
Create Date: 2025-03-08 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20250308_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=32), nullable=False),
        sa.Column("priority", sa.String(length=16), nullable=False),
        sa.Column("schema_id", sa.String(length=128), nullable=True),
        sa.Column("tenant", sa.String(length=64), nullable=True),
        sa.Column("engine", sa.String(length=32), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_jobs_priority", "jobs", ["priority"])
    op.create_index("ix_jobs_state", "jobs", ["state"])

    op.create_table(
        "job_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id"),
            nullable=True,
        ),
        sa.Column("engine", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_job_attempts_job_id", "job_attempts", ["job_id"])

    op.create_table(
        "artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("jobs.id"),
            nullable=True,
        ),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_artifacts_job_id", "artifacts", ["job_id"])

    op.create_table(
        "schemas",
        sa.Column("id", sa.String(length=128), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "selectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("schema_id", sa.String(length=128), nullable=True),
        sa.Column("group_name", sa.String(length=128), nullable=True),
        sa.Column("field", sa.String(length=128), nullable=False),
        sa.Column("selector", sa.Text(), nullable=False),
        sa.Column("item_selector", sa.Text(), nullable=True),
        sa.Column("attribute", sa.String(length=128), nullable=True),
        sa.Column("data_type", sa.String(length=32), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_selectors_schema_id", "selectors", ["schema_id"])
    op.create_index("ix_selectors_group_name", "selectors", ["group_name"])

    op.create_table(
        "selector_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("schema_id", sa.String(length=128), nullable=True),
        sa.Column("group_name", sa.String(length=128), nullable=True),
        sa.Column("field", sa.String(length=128), nullable=False),
        sa.Column("selector", sa.Text(), nullable=False),
        sa.Column("item_selector", sa.Text(), nullable=True),
        sa.Column("attribute", sa.String(length=128), nullable=True),
        sa.Column("data_type", sa.String(length=32), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=True),
        sa.Column("success_count", sa.Integer(), nullable=True),
        sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_selector_candidates_schema_id",
        "selector_candidates",
        ["schema_id"],
    )
    op.create_index(
        "ix_selector_candidates_group_name",
        "selector_candidates",
        ["group_name"],
    )

    op.create_table(
        "proxy_policies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("proxy_url", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("domain", name="uq_proxy_policies_domain"),
    )
    op.create_index("ix_proxy_policies_domain", "proxy_policies", ["domain"])

    op.create_table(
        "identities",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=True),
        sa.Column("fingerprint", postgresql.JSONB(), nullable=True),
        sa.Column("cookies_encrypted", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("use_count", sa.Integer(), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_identities_tenant", "identities", ["tenant"])


def downgrade() -> None:
    op.drop_index("ix_identities_tenant", table_name="identities")
    op.drop_table("identities")
    op.drop_index("ix_proxy_policies_domain", table_name="proxy_policies")
    op.drop_table("proxy_policies")
    op.drop_index(
        "ix_selector_candidates_group_name",
        table_name="selector_candidates",
    )
    op.drop_index(
        "ix_selector_candidates_schema_id",
        table_name="selector_candidates",
    )
    op.drop_table("selector_candidates")
    op.drop_index("ix_selectors_group_name", table_name="selectors")
    op.drop_index("ix_selectors_schema_id", table_name="selectors")
    op.drop_table("selectors")
    op.drop_table("schemas")
    op.drop_index("ix_artifacts_job_id", table_name="artifacts")
    op.drop_table("artifacts")
    op.drop_index("ix_job_attempts_job_id", table_name="job_attempts")
    op.drop_table("job_attempts")
    op.drop_index("ix_jobs_state", table_name="jobs")
    op.drop_index("ix_jobs_priority", table_name="jobs")
    op.drop_table("jobs")
