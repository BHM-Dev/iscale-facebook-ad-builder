"""add pacing and numbers-used strategy notes to scraped ads"""

from alembic import op


revision = 'a2b3c4d5e6f7'
# The strategy-notes migration was introduced on a parallel branch after the
# token migration. Merge both existing heads here so this deploy restores one
# authoritative head without rewriting already-deployed revisions.
down_revision = ('a1b2c3d4e5f6', 'z1a2b3c4d5e6')
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS pacing VARCHAR")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS numbers_used VARCHAR")


def downgrade() -> None:
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS numbers_used")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS pacing")
