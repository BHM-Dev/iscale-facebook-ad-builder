"""Track when each campaign / ad set row was last refreshed from Meta.

Revision ID: d6e8f0a2b4c6
Revises: c5d7e9f1a3b5
"""

from alembic import op


revision = "d6e8f0a2b4c6"
down_revision = "c5d7e9f1a3b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # init_db.py creates model columns before Alembic runs on a fresh install;
    # IF NOT EXISTS keeps this migration safe on both paths.
    op.execute("ALTER TABLE facebook_adsets ADD COLUMN IF NOT EXISTS synced_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE facebook_campaigns ADD COLUMN IF NOT EXISTS synced_at TIMESTAMP WITH TIME ZONE")


def downgrade() -> None:
    op.execute("ALTER TABLE facebook_campaigns DROP COLUMN IF EXISTS synced_at")
    op.execute("ALTER TABLE facebook_adsets DROP COLUMN IF EXISTS synced_at")
