"""add media_url to scraped_ads

Revision ID: o3k1l7m8n0j6
Revises: n2j0k6l7m9i5
Create Date: 2026-06-03

Stores the primary image or video thumbnail URL returned by the
Facebook Ads Library API (snapshot_url) or extracted by Playwright.
URLs are temporary Facebook CDN links — they may expire after 24-72h.
"""
from alembic import op


revision = 'o3k1l7m8n0j6'
down_revision = 'n2j0k6l7m9i5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS media_url VARCHAR"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE scraped_ads DROP COLUMN IF EXISTS media_url"
    )
