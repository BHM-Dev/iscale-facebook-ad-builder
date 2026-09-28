"""preserve source evidence for research test decisions

Revision ID: f2a1b0c9d8e7
Revises: e1f0a9b8c7d6
"""
from alembic import op
import sqlalchemy as sa

revision = "f2a1b0c9d8e7"
down_revision = "e1f0a9b8c7d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("research_test_backlog_items"):
        return
    op.execute("ALTER TABLE research_test_backlog_items ADD COLUMN IF NOT EXISTS source_snapshot JSON")


def downgrade() -> None:
    op.execute("ALTER TABLE research_test_backlog_items DROP COLUMN IF EXISTS source_snapshot")
