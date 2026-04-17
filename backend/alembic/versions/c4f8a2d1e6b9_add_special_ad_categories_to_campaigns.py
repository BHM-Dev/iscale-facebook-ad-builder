"""add special_ad_categories to campaigns

Revision ID: c4f8a2d1e6b9
Revises: b7d3e1f2a9c5
Create Date: 2026-04-17 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'c4f8a2d1e6b9'
down_revision = 'b7d3e1f2a9c5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'facebook_campaigns',
        sa.Column('special_ad_categories', sa.JSON(), nullable=True)
    )


def downgrade():
    op.drop_column('facebook_campaigns', 'special_ad_categories')
