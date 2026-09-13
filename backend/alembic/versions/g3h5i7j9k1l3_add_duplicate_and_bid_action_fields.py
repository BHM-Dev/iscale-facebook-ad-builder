"""add duplicate action fields to auto_pause_rules (Phase 2: Duplicate + bid actions)

Revision ID: g3h5i7j9k1l3
Revises: f2g4h6i8j0k2
Create Date: 2026-09-13

Adds the config fields for the Duplicate rule action (all-ads-vs-empty, name suffix,
append-number, pause-original, repeat) per AdBuilder-BulkRules-Feature-Brief.md §8. Bid
actions (increase_bid/decrease_bid) need no new columns — they reuse the existing
`action`/`budget_adjust_pct` columns from the f2g4h6i8j0k2 migration.

Defaults chosen to match Birch's own Duplicate action, verified live against its actual
config screen rather than guessed. All columns nullable/defaulted so every pre-existing
row, and every row using a non-duplicate action, is unaffected.
"""
from alembic import op


revision = 'g3h5i7j9k1l3'
down_revision = 'f2g4h6i8j0k2'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE auto_pause_rules ADD COLUMN IF NOT EXISTS duplicate_all_ads BOOLEAN DEFAULT TRUE")
    op.execute("ALTER TABLE auto_pause_rules ADD COLUMN IF NOT EXISTS duplicate_name_suffix VARCHAR DEFAULT '- Copy'")
    op.execute("ALTER TABLE auto_pause_rules ADD COLUMN IF NOT EXISTS duplicate_append_number BOOLEAN DEFAULT FALSE")
    op.execute("ALTER TABLE auto_pause_rules ADD COLUMN IF NOT EXISTS duplicate_pause_original BOOLEAN DEFAULT FALSE")
    op.execute("ALTER TABLE auto_pause_rules ADD COLUMN IF NOT EXISTS duplicate_repeat BOOLEAN DEFAULT FALSE")


def downgrade() -> None:
    op.execute("ALTER TABLE auto_pause_rules DROP COLUMN IF EXISTS duplicate_repeat")
    op.execute("ALTER TABLE auto_pause_rules DROP COLUMN IF EXISTS duplicate_pause_original")
    op.execute("ALTER TABLE auto_pause_rules DROP COLUMN IF EXISTS duplicate_append_number")
    op.execute("ALTER TABLE auto_pause_rules DROP COLUMN IF EXISTS duplicate_name_suffix")
    op.execute("ALTER TABLE auto_pause_rules DROP COLUMN IF EXISTS duplicate_all_ads")
