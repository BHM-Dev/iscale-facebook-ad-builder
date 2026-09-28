"""add durable research test launch claim

Revision ID: e1f0a9b8c7d6
Revises: d0e9f8a7b6c5
"""
from alembic import op
import sqlalchemy as sa

revision = "e1f0a9b8c7d6"
down_revision = "d0e9f8a7b6c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if not sa.inspect(bind).has_table("research_test_backlog_items"):
        return
    op.execute("ALTER TABLE research_test_backlog_items ADD COLUMN IF NOT EXISTS launch_claim_id VARCHAR")
    op.execute("CREATE INDEX IF NOT EXISTS ix_research_test_backlog_items_launch_claim_id ON research_test_backlog_items (launch_claim_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_research_test_backlog_items_launch_claim_id")
    op.execute("ALTER TABLE research_test_backlog_items DROP COLUMN IF EXISTS launch_claim_id")
