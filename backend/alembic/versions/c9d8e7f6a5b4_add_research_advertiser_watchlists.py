"""add research advertiser watchlists

Revision ID: c9d8e7f6a5b4
Revises: a4b5c6d7e8f9
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa


revision = 'c9d8e7f6a5b4'
down_revision = 'a4b5c6d7e8f9'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('research_advertiser_watchlists'):
        return
    op.create_table(
        'research_advertiser_watchlists',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('vertical_id', sa.String(), nullable=False),
        sa.Column('advertiser', sa.String(), nullable=False),
        sa.Column('advertiser_key', sa.String(), nullable=False),
        sa.Column('created_by', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('last_viewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
        sa.UniqueConstraint('created_by', 'vertical_id', 'advertiser_key', name='uq_research_watchlist_advertiser'),
    )
    op.create_index('ix_research_advertiser_watchlists_vertical_id', 'research_advertiser_watchlists', ['vertical_id'])
    op.create_index('ix_research_advertiser_watchlists_created_by', 'research_advertiser_watchlists', ['created_by'])


def downgrade() -> None:
    op.drop_table('research_advertiser_watchlists')
