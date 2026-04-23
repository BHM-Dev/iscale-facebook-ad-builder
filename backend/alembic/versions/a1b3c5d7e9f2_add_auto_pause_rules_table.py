"""Add auto_pause_rules table.

Revision ID: a1b3c5d7e9f2
Revises: f4b2c8d9e1a7
Create Date: 2026-04-23

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'a1b3c5d7e9f2'
down_revision: Union[str, Sequence[str], None] = 'f4b2c8d9e1a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'auto_pause_rules',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('adset_id', sa.String(), nullable=False),
        sa.Column('metric', sa.String(), nullable=False),
        sa.Column('operator', sa.String(), nullable=False, server_default='greater_than'),
        sa.Column('threshold', sa.Integer(), nullable=False),
        sa.Column('min_spend', sa.Integer(), nullable=False, server_default='20'),
        sa.Column('is_active', sa.Boolean(), nullable=True, server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=True),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('triggered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('trigger_reason', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['adset_id'], ['facebook_adsets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_auto_pause_rules_adset_id', 'auto_pause_rules', ['adset_id'])
    op.create_index('ix_auto_pause_rules_is_active', 'auto_pause_rules', ['is_active'])


def downgrade() -> None:
    op.drop_index('ix_auto_pause_rules_is_active', table_name='auto_pause_rules')
    op.drop_index('ix_auto_pause_rules_adset_id', table_name='auto_pause_rules')
    op.drop_table('auto_pause_rules')
