"""add description to generated ads

Revision ID: h8i6j4k2l0m8
Revises: g7h5j3k1l9m7
"""

from alembic import op


revision = "h8i6j4k2l0m8"
down_revision = "g7h5j3k1l9m7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS description TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE generated_ads DROP COLUMN IF EXISTS description")
