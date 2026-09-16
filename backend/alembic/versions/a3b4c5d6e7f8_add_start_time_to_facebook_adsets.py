"""add start time to locally saved Facebook ad sets"""

from alembic import op


revision = 'a3b4c5d6e7f8'
down_revision = 'a2b3c4d5e6f7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE facebook_adsets ADD COLUMN IF NOT EXISTS start_time TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE facebook_adsets DROP COLUMN IF EXISTS start_time")
