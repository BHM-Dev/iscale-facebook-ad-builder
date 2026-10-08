"""add buyer verdict fields to research tests"""

from alembic import op


revision = "b4c6e8f0a2d4"
down_revision = "d6e8f0a2b4c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE research_test_backlog_items ADD COLUMN IF NOT EXISTS verdict VARCHAR")
    op.execute("ALTER TABLE research_test_backlog_items ADD COLUMN IF NOT EXISTS verdict_reason TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE research_test_backlog_items DROP COLUMN IF EXISTS verdict_reason")
    op.execute("ALTER TABLE research_test_backlog_items DROP COLUMN IF EXISTS verdict")
