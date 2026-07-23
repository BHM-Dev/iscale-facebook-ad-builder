"""add fb_account_id to campaigns and adsets (account-scoped lists)

Revision ID: s7o5p1q2r4n0
Revises: r6n4o0p1q3m9
Create Date: 2026-07-23

Stores the Meta ad account each synced campaign/adset belongs to, so the saved
lists (Campaign Performance) can be scoped to the active account. Also the
foundational resolution layer for hard per-account enforcement.

Populated at sync time (sync_from_meta knows the account it's syncing). Existing
rows stay NULL until re-synced; read_saved_adsets treats NULL as "unscoped"
(shown to all) during the transition, then scoping tightens as data is tagged.
All columns additive/nullable — safe on re-run.
"""
from alembic import op


revision = 's7o5p1q2r4n0'
down_revision = 'r6n4o0p1q3m9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE facebook_campaigns ADD COLUMN IF NOT EXISTS fb_account_id VARCHAR")
    op.execute("ALTER TABLE facebook_adsets    ADD COLUMN IF NOT EXISTS fb_account_id VARCHAR")
    op.execute("CREATE INDEX IF NOT EXISTS ix_facebook_adsets_fb_account_id ON facebook_adsets (fb_account_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_facebook_campaigns_fb_account_id ON facebook_campaigns (fb_account_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_facebook_campaigns_fb_account_id")
    op.execute("DROP INDEX IF EXISTS ix_facebook_adsets_fb_account_id")
    op.execute("ALTER TABLE facebook_adsets    DROP COLUMN IF EXISTS fb_account_id")
    op.execute("ALTER TABLE facebook_campaigns DROP COLUMN IF EXISTS fb_account_id")
