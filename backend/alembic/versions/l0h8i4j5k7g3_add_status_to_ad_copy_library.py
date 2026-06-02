"""add status to ad_copy_library

Revision ID: l0h8i4j5k7g3
Revises: k9g7h3i4j6f2
Create Date: 2026-06-02

"""
from alembic import op
import sqlalchemy as sa

revision = 'l0h8i4j5k7g3'
down_revision = 'k9g7h3i4j6f2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ad_copy_library ADD COLUMN IF NOT EXISTS status VARCHAR"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ad_copy_library DROP COLUMN IF EXISTS status"
    )
