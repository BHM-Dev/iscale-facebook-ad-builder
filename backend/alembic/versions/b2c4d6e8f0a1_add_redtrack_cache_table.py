"""Add redtrack_cache table.

Revision ID: b2c4d6e8f0a1
Revises: a1b3c5d7e9f2
Create Date: 2026-04-26

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b2c4d6e8f0a1'
down_revision: Union[str, Sequence[str], None] = 'a1b3c5d7e9f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    import sqlalchemy as sa_inspect
    if sa_inspect.inspect(bind).has_table('redtrack_cache'):
        return
    op.create_table(
        'redtrack_cache',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('fb_adset_id', sa.String(), nullable=False),
        sa.Column('date_from', sa.Date(), nullable=False),
        sa.Column('date_to', sa.Date(), nullable=False),
        sa.Column('conversions', sa.Integer(), nullable=True),
        sa.Column('revenue', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('cost', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('profit', sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column('roas', sa.Numeric(precision=6, scale=2), nullable=True),
        sa.Column('cpl', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('clicks', sa.Integer(), nullable=True),
        sa.Column('quality_rate', sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_redtrack_cache_adset_id', 'redtrack_cache', ['fb_adset_id'])
    op.create_index('ix_redtrack_cache_date', 'redtrack_cache', ['date_from', 'date_to'])


def downgrade() -> None:
    op.drop_index('ix_redtrack_cache_date', table_name='redtrack_cache')
    op.drop_index('ix_redtrack_cache_adset_id', table_name='redtrack_cache')
    op.drop_table('redtrack_cache')
