"""Add missing columns to facebook tables (idempotent catch-up).

Production DB was stamped at d8f2e1a7b4c9 via 'alembic stamp head' without
actually running the baseline DDL. Several columns added in the baseline
migration are therefore absent. This migration adds each missing column with
IF NOT EXISTS so it is safe to run even on a fully up-to-date schema.

Revision ID: e3a1f9b2c8d4
Revises: d8f2e1a7b4c9
Create Date: 2026-04-23

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e3a1f9b2c8d4'
down_revision: Union[str, Sequence[str], None] = 'd8f2e1a7b4c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add columns that may be absent on databases that were stamp-migrated."""

    # ── facebook_campaigns ────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE facebook_campaigns
            ADD COLUMN IF NOT EXISTS budget_schedule_type VARCHAR,
            ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT now()
    """)

    # ── facebook_adsets ───────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE facebook_adsets
            ADD COLUMN IF NOT EXISTS budget_schedule_type VARCHAR,
            ADD COLUMN IF NOT EXISTS bid_amount INTEGER
    """)

    # ── facebook_ads ──────────────────────────────────────────────────────
    # Video-support columns added after initial launch
    op.execute("""
        ALTER TABLE facebook_ads
            ADD COLUMN IF NOT EXISTS media_type  VARCHAR,
            ADD COLUMN IF NOT EXISTS video_url   VARCHAR,
            ADD COLUMN IF NOT EXISTS video_id    VARCHAR,
            ADD COLUMN IF NOT EXISTS thumbnail_url VARCHAR
    """)


def downgrade() -> None:
    """Remove the columns added above (only safe on dev / test DBs)."""

    op.execute("""
        ALTER TABLE facebook_ads
            DROP COLUMN IF EXISTS thumbnail_url,
            DROP COLUMN IF EXISTS video_id,
            DROP COLUMN IF EXISTS video_url,
            DROP COLUMN IF EXISTS media_type
    """)

    op.execute("""
        ALTER TABLE facebook_adsets
            DROP COLUMN IF EXISTS bid_amount,
            DROP COLUMN IF EXISTS budget_schedule_type
    """)

    op.execute("""
        ALTER TABLE facebook_campaigns
            DROP COLUMN IF EXISTS updated_at,
            DROP COLUMN IF EXISTS budget_schedule_type
    """)
