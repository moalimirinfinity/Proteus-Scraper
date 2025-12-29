"""Add storage state to identities.

Revision ID: 20250309_0002
Revises: 20250308_0001
Create Date: 2025-03-09 00:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "20250309_0002"
down_revision = "20250308_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("identities", sa.Column("storage_state_encrypted", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("identities", "storage_state_encrypted")
