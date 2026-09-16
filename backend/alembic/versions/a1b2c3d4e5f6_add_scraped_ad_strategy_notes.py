"""add nullable strategy notes to scraped ads"""
from alembic import op

revision = 'a1b2c3d4e5f6'
down_revision = 'aa1b2c3d4e56'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS hook_type VARCHAR")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS persona VARCHAR")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS promise TEXT")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS proof_type VARCHAR")
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS funnel_stage VARCHAR")


def downgrade() -> None:
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS funnel_stage")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS proof_type")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS promise")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS persona")
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS hook_type")
