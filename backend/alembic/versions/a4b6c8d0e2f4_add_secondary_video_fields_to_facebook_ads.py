"""Persist the Stories/Reels video on dual-placement ads.

Revision ID: a4b6c8d0e2f4
Revises: b7c8d9e0f1a2
"""

from alembic import op


revision = "a4b6c8d0e2f4"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # init_db.py creates model columns before Alembic runs on a fresh install;
    # IF NOT EXISTS keeps this migration safe on both paths.
    op.execute("ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS secondary_video_url VARCHAR")
    op.execute("ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS secondary_video_id VARCHAR")


def downgrade() -> None:
    op.execute("ALTER TABLE facebook_ads DROP COLUMN IF EXISTS secondary_video_id")
    op.execute("ALTER TABLE facebook_ads DROP COLUMN IF EXISTS secondary_video_url")
