"""add Facebook ad launch provenance

Revision ID: aa2b3c4d5e6f
Revises: z1a2b3c4d5e6
Create Date: 2026-10-08

Stores the minimal local context needed to identify an approved Drive creative
in the existing Campaign Performance ad-level table. Meta remains the source
of truth for all delivery metrics.
"""
from alembic import op


revision = 'aa2b3c4d5e6f'
down_revision = 'b4c6e8f0a2d4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS source_type VARCHAR")
    op.execute("ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS source_category VARCHAR")


def downgrade() -> None:
    op.execute("ALTER TABLE facebook_ads DROP COLUMN IF EXISTS source_category")
    op.execute("ALTER TABLE facebook_ads DROP COLUMN IF EXISTS source_type")
