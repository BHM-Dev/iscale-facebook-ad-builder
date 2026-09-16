"""add pacing and numbers-used strategy notes to scraped ads"""

from alembic import op


revision = 'a2b3c4d5e6f7'
# The prior version of this migration merged down_revision with 'z1a2b3c4d5e6'
# on the theory that it was a second, divergent head. It wasn't: z1a2b3c4d5e6
# is an ANCESTOR several steps back in this same linear chain (via
# f2g4h6i8j0k2 -> ... -> a1b2c3d4e5f6, confirmed by walking the full revision
# graph and confirming exactly one file in this directory has
# down_revision='z1a2b3c4d5e6' — the pre-existing f2g4h6i8j0k2, already
# deployed long ago). There was never a real branch to merge; this is a plain
# single-parent migration like every other one in this repo (pre-push review).
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS pacing VARCHAR")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS numbers_used VARCHAR")


def downgrade() -> None:
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS numbers_used")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS pacing")
