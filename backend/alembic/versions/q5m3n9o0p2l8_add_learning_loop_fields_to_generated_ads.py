"""add learning loop attribution fields to generated_ads

Revision ID: q5m3n9o0p2l8
Revises: p4l2m8n9o1k7
Create Date: 2026-07-17

Adds attribution + performance columns to generated_ads so a pushed
creative can be joined back to Meta and to RedTrack revenue data.

Primary attribution join (resolved Phase 0, 2026-07-17):
    generated_ads.fb_ad_id  ->  RedTrack sub1 (= Meta ad id)

fb_adset_id / fb_campaign_id are kept for rollups, not the primary join.
All columns are additive and nullable — safe on re-run.
"""
from alembic import op


revision = 'q5m3n9o0p2l8'
down_revision = 'p4l2m8n9o1k7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS angle          VARCHAR")
    op.execute("ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS source_ad_id   VARCHAR")
    op.execute("ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS profile_id     VARCHAR")
    op.execute("ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS fb_campaign_id VARCHAR")
    op.execute("ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS fb_adset_id    VARCHAR")
    op.execute("ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS fb_creative_id VARCHAR")
    op.execute("ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS revenue        NUMERIC(10,2)")
    op.execute("ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS profit         NUMERIC(10,2)")
    op.execute("ALTER TABLE generated_ads ADD COLUMN IF NOT EXISTS last_synced_at TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS ix_generated_ads_fb_adset_id ON generated_ads (fb_adset_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_generated_ads_fb_adset_id")
    op.execute("ALTER TABLE generated_ads DROP COLUMN IF EXISTS last_synced_at")
    op.execute("ALTER TABLE generated_ads DROP COLUMN IF EXISTS profit")
    op.execute("ALTER TABLE generated_ads DROP COLUMN IF EXISTS revenue")
    op.execute("ALTER TABLE generated_ads DROP COLUMN IF EXISTS fb_creative_id")
    op.execute("ALTER TABLE generated_ads DROP COLUMN IF EXISTS fb_adset_id")
    op.execute("ALTER TABLE generated_ads DROP COLUMN IF EXISTS fb_campaign_id")
    op.execute("ALTER TABLE generated_ads DROP COLUMN IF EXISTS profile_id")
    op.execute("ALTER TABLE generated_ads DROP COLUMN IF EXISTS source_ad_id")
    op.execute("ALTER TABLE generated_ads DROP COLUMN IF EXISTS angle")
