"""Add all remaining missing columns to facebook tables.

The production DB was bootstrapped by init_db.py from an older version of the
models. Many columns added since then were only stamped, never applied via DDL.
This migration adds every column that may be absent using ADD COLUMN IF NOT
EXISTS so it is safe to run on any DB state.

Covers columns missed by e3a1f9b2c8d4 (first catch-up migration).

Revision ID: f4b2c8d9e1a7
Revises: e3a1f9b2c8d4
Create Date: 2026-04-23

"""
from typing import Sequence, Union
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f4b2c8d9e1a7'
down_revision: Union[str, Sequence[str], None] = 'e3a1f9b2c8d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add all columns that may be absent on databases bootstrapped from an
    older version of init_db.py / models.py."""

    # ── facebook_campaigns ────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE facebook_campaigns
            ADD COLUMN IF NOT EXISTS lifetime_budget      INTEGER,
            ADD COLUMN IF NOT EXISTS end_time             TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS bid_strategy         VARCHAR,
            ADD COLUMN IF NOT EXISTS special_ad_categories JSONB
    """)

    # ── facebook_adsets ───────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE facebook_adsets
            ADD COLUMN IF NOT EXISTS lifetime_budget  INTEGER,
            ADD COLUMN IF NOT EXISTS end_time         TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS bid_strategy     VARCHAR
    """)

    # ── facebook_ads ──────────────────────────────────────────────────────
    op.execute("""
        ALTER TABLE facebook_ads
            ADD COLUMN IF NOT EXISTS creative_name  VARCHAR,
            ADD COLUMN IF NOT EXISTS website_url    VARCHAR,
            ADD COLUMN IF NOT EXISTS fb_creative_id VARCHAR
    """)


def downgrade() -> None:
    """Remove the columns added above (only safe on dev / test DBs)."""

    op.execute("""
        ALTER TABLE facebook_ads
            DROP COLUMN IF EXISTS fb_creative_id,
            DROP COLUMN IF EXISTS website_url,
            DROP COLUMN IF EXISTS creative_name
    """)

    op.execute("""
        ALTER TABLE facebook_adsets
            DROP COLUMN IF EXISTS bid_strategy,
            DROP COLUMN IF EXISTS end_time,
            DROP COLUMN IF EXISTS lifetime_budget
    """)

    op.execute("""
        ALTER TABLE facebook_campaigns
            DROP COLUMN IF EXISTS special_ad_categories,
            DROP COLUMN IF EXISTS bid_strategy,
            DROP COLUMN IF EXISTS end_time,
            DROP COLUMN IF EXISTS lifetime_budget
    """)
