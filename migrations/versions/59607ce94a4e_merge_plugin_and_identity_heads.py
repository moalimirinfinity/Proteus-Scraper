"""merge plugin and identity heads

Revision ID: 59607ce94a4e
Revises: 20250309_0002, 20250310_0002
Create Date: 2025-12-29 12:49:22.256584

"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = '59607ce94a4e'
down_revision = ('20250309_0002', '20250310_0002')
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
