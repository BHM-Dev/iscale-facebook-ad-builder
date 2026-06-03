"""add missing scraped_ads columns (is_saved, seen_count, first_seen, last_seen, content_hash, facebook_page_id)

Revision ID: n2j0k6l7m9i5
Revises: m1i9j5k6l8h4
Create Date: 2026-06-03

These columns were added to the model but never had explicit migrations —
they appeared in the baseline CREATE TABLE after the VPS table was already
created. This migration backfills them safely with IF NOT EXISTS.
"""
from alembic import op
import sqlalchemy as sa


revision = 'n2j0k6l7m9i5'
down_revision = 'm1i9j5k6l8h4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # is_saved — user-curated save flag (the column causing the current error)
    op.execute(
        "ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS is_saved BOOLEAN NOT NULL DEFAULT false"
    )
    # seen_count — number of times this ad appeared in scrapes
    op.execute(
        "ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS seen_count INTEGER DEFAULT 1"
    )
    # first_seen — first scrape timestamp
    op.execute(
        "ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS first_seen TIMESTAMPTZ DEFAULT now()"
    )
    # last_seen — last scrape timestamp (used for active-proxy logic)
    op.execute(
        "ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ DEFAULT now()"
    )
    # content_hash — deduplication hash
    op.execute(
        "ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS content_hash VARCHAR"
    )
    # facebook_page_id — FK to facebook_pages (nullable, no FK constraint added here)
    op.execute(
        "ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS facebook_page_id VARCHAR"
    )
    # angle_tag is handled by the previous migration (m1i9j5k6l8h4) — skipped here


def downgrade() -> None:
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS is_saved")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS seen_count")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS first_seen")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS last_seen")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS content_hash")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS facebook_page_id")
