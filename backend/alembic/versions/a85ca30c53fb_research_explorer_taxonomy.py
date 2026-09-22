"""add research explorer taxonomy and media catalog fields

Revision ID: a85ca30c53fb
Revises: i9j7k5l3m1n9
Create Date: 2026-09-21

The original commit picked revision id a2b3c4d5e6f7, which already belonged
to a2b3c4d5e6f7_add_pacing_and_numbers_used_to_scraped_ads.py (a genuine
hash collision), and pointed down_revision at z1a2b3c4d5e6 instead of the
actual current head. Both caused `alembic heads` to report multiple heads
and break the auto-deploy. i9j7k5l3m1n9 is the confirmed single head as of
the last successfully deployed develop commit (b25ce0d).
"""
from alembic import op

revision = "a85ca30c53fb"
down_revision = "i9j7k5l3m1n9"
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
