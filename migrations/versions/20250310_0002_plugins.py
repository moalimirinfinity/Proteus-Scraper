"""Add plugin configuration tables.

Revision ID: 20250310_0002
Revises: 20250308_0001
Create Date: 2025-03-10 00:00:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20250310_0002"
down_revision = "20250308_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("schemas", sa.Column("plugins", postgresql.JSONB(), nullable=True))

    op.create_table(
        "tenant_plugins",
        sa.Column("tenant", sa.String(length=64), primary_key=True),
        sa.Column("plugins", postgresql.JSONB(), nullable=True),
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


def downgrade() -> None:
    op.drop_table("tenant_plugins")
    op.drop_column("schemas", "plugins")
