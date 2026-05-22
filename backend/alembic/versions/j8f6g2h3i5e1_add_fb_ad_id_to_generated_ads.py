"""add fb_ad_id to generated_ads

Revision ID: j8f6g2h3i5e1
Revises: i7e5f1g2h4d0
Create Date: 2026-05-21

Links a GeneratedAd record to its Meta ad ID after batch push, so the
Iterate flow can restore overlay fields (offer line, logo) from the local DB.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'j8f6g2h3i5e1'
down_revision = 'i7e5f1g2h4d0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('generated_ads', sa.Column('fb_ad_id', sa.String(), nullable=True))
    op.create_index('ix_generated_ads_fb_ad_id', 'generated_ads', ['fb_ad_id'], unique=False)


def downgrade():
    op.drop_index('ix_generated_ads_fb_ad_id', table_name='generated_ads')
    op.drop_column('generated_ads', 'fb_ad_id')
