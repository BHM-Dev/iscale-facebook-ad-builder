"""add workspace-shared research boards

Revision ID: aa1b2c3d4e5
Revises: g3h5i7j9k1l3
"""
from alembic import op
import sqlalchemy as sa


revision = 'aa1b2c3d4e5'
down_revision = 'g3h5i7j9k1l3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('research_boards'):
        op.create_table(
            'research_boards',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('vertical_id', sa.String(), nullable=True),
            sa.Column('created_by', sa.String(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    if not inspector.has_table('research_board_items'):
        op.create_table(
            'research_board_items',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('board_id', sa.String(), sa.ForeignKey('research_boards.id', ondelete='CASCADE'), nullable=False),
            sa.Column('scraped_ad_id', sa.String(), sa.ForeignKey('scraped_ads.id', ondelete='CASCADE'), nullable=False),
            sa.Column('sort_order', sa.Integer(), nullable=True, server_default='0'),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint('board_id', 'scraped_ad_id', name='uq_research_board_item'),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table('research_board_items'):
        op.drop_table('research_board_items')
    if inspector.has_table('research_boards'):
        op.drop_table('research_boards')
