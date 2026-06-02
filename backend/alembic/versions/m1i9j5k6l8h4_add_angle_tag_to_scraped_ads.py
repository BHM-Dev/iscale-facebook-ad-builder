"""add angle_tag to scraped_ads

Revision ID: m1i9j5k6l8h4
Revises: l0h8i4j5k7g3
Create Date: 2026-06-02 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'm1i9j5k6l8h4'
down_revision = 'l0h8i4j5k7g3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE scraped_ads ADD COLUMN IF NOT EXISTS angle_tag VARCHAR")


def downgrade() -> None:
    op.execute("ALTER TABLE scraped_ads DROP COLUMN IF EXISTS angle_tag")
