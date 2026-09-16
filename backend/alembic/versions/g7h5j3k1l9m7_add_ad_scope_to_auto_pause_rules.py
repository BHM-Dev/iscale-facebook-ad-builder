"""Add ad-level scope and Meta ad identity to auto-pause rules."""

from alembic import op


revision = 'g7h5j3k1l9m7'
down_revision = ('a3b4c5d6e7f8', 'f2g4h6i8j0k2')
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE auto_pause_rules ADD COLUMN IF NOT EXISTS scope VARCHAR NOT NULL DEFAULT 'adset'")
    op.execute("ALTER TABLE auto_pause_rules ADD COLUMN IF NOT EXISTS fb_ad_id VARCHAR")
    op.execute("ALTER TABLE auto_pause_rules ADD COLUMN IF NOT EXISTS ad_name VARCHAR")
    op.execute("CREATE INDEX IF NOT EXISTS ix_auto_pause_rules_fb_ad_id ON auto_pause_rules (fb_ad_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_auto_pause_rules_fb_ad_id")
    op.execute("ALTER TABLE auto_pause_rules DROP COLUMN IF EXISTS ad_name")
    op.execute("ALTER TABLE auto_pause_rules DROP COLUMN IF EXISTS fb_ad_id")
    op.execute("ALTER TABLE auto_pause_rules DROP COLUMN IF EXISTS scope")
