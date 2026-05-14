"""add overlay and niche fields to generated_ads

Revision ID: i7e5f1g2h4d0
Revises: h6d4e0f1g3c9
Create Date: 2026-05-14

Stores text overlay settings alongside each generated image so the
Iterate / Remix workflows can reconstruct what was baked in.
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'i7e5f1g2h4d0'
down_revision = 'h6d4e0f1g3c9'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('generated_ads', sa.Column('niche', sa.String(), nullable=True))
    op.add_column('generated_ads', sa.Column('overlay_enabled', sa.Boolean(), nullable=True, server_default='false'))
    op.add_column('generated_ads', sa.Column('overlay_niche_line', sa.String(), nullable=True))
    op.add_column('generated_ads', sa.Column('overlay_offer_line', sa.String(), nullable=True))
    op.add_column('generated_ads', sa.Column('overlay_cta', sa.String(), nullable=True))
    op.add_column('generated_ads', sa.Column('overlay_logo_url', sa.String(), nullable=True))


def downgrade():
    op.drop_column('generated_ads', 'overlay_logo_url')
    op.drop_column('generated_ads', 'overlay_cta')
    op.drop_column('generated_ads', 'overlay_offer_line')
    op.drop_column('generated_ads', 'overlay_niche_line')
    op.drop_column('generated_ads', 'overlay_enabled')
    op.drop_column('generated_ads', 'niche')
