"""add ad library intel fields

Revision ID: v0r8s4t5u7q3
Revises: u9q7r3s4t6p2
Create Date: 2026-08-01

Adds fields used by the Chrome-assisted Ad Library import flow. These are
directional creative-intel fields, not official spend/impression metrics.
"""
from alembic import op


revision = 'v0r8s4t5u7q3'
down_revision = 'u9q7r3s4t6p2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS destination_domain VARCHAR")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS source_query VARCHAR")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS rank_position INTEGER")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS sort_mode VARCHAR")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS is_multiple_versions BOOLEAN DEFAULT false")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS video_urls JSON")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS thumbnail_url VARCHAR")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS creative_intel JSON")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS volume_score INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS volume_score")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS creative_intel")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS thumbnail_url")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS video_urls")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS is_multiple_versions")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS sort_mode")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS rank_position")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS source_query")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS destination_domain")
