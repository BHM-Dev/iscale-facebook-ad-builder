"""add ad_copy_library table

Revision ID: k9g7h3i4j6f2
Revises: j8f6g2h3i5e1
Create Date: 2026-06-02

"""
from alembic import op
import sqlalchemy as sa

revision = 'k9g7h3i4j6f2'
down_revision = 'j8f6g2h3i5e1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # has_table guard — init_db.py runs Base.metadata.create_all() before Alembic,
    # so the table may already exist on the first deploy after this migration is added.
    bind = op.get_bind()
    if sa.inspect(bind).has_table('ad_copy_library'):
        return

    op.create_table(
        'ad_copy_library',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('fb_ad_id', sa.String(), nullable=False),
        sa.Column('fb_adset_id', sa.String(), nullable=True),
        sa.Column('adset_name', sa.String(), nullable=True),
        sa.Column('niche', sa.String(), nullable=True),
        sa.Column('headline', sa.Text(), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('cta_type', sa.String(), nullable=True),
        sa.Column('spend', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('cpl', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('is_pinned', sa.Boolean(), nullable=True, server_default=sa.text('false')),
        sa.Column('imported_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('fb_ad_id'),
    )
    op.create_index('ix_ad_copy_library_fb_ad_id', 'ad_copy_library', ['fb_ad_id'])
    op.create_index('ix_ad_copy_library_fb_adset_id', 'ad_copy_library', ['fb_adset_id'])
    op.create_index('ix_ad_copy_library_niche', 'ad_copy_library', ['niche'])


def downgrade() -> None:
    op.drop_index('ix_ad_copy_library_niche', table_name='ad_copy_library')
    op.drop_index('ix_ad_copy_library_fb_adset_id', table_name='ad_copy_library')
    op.drop_index('ix_ad_copy_library_fb_ad_id', table_name='ad_copy_library')
    op.drop_table('ad_copy_library')
