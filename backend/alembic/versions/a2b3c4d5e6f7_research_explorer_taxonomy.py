"""add research explorer taxonomy and media catalog fields

Revision ID: a2b3c4d5e6f7
Revises: z1a2b3c4d5e6
Create Date: 2026-09-21
"""
from alembic import op

revision = "a2b3c4d5e6f7"
down_revision = "z1a2b3c4d5e6"
branch_labels = None
depends_on = None

def upgrade() -> None:
    for column in (
        "creative_tags JSON", "cta_type VARCHAR", "page_type VARCHAR",
        "video_length_seconds INTEGER", "media_preview_url VARCHAR",
        "media_width INTEGER", "media_height INTEGER", "taxonomy_source VARCHAR",
        "taxonomy_confidence VARCHAR",
    ):
        op.execute(f"ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS {column}")
    # CONCURRENTLY avoids an ACCESS EXCLUSIVE lock on scraped_ads during deploy;
    # it can't run inside the migration's normal transaction, hence autocommit_block.
    with op.get_context().autocommit_block():
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_scraped_ads_last_seen ON scraped_ads (last_seen DESC)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_scraped_ads_cta_type ON scraped_ads (cta_type)")
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_scraped_ads_page_type ON scraped_ads (page_type)")

def downgrade() -> None:
    for column in ("taxonomy_confidence", "taxonomy_source", "media_height", "media_width", "media_preview_url", "video_length_seconds", "page_type", "cta_type", "creative_tags"):
        op.execute(f"ALTER TABLE scraped_ads DROP COLUMN IF EXISTS {column}")
