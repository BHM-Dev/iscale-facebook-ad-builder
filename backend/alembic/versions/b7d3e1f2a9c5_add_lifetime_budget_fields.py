"""add lifetime budget fields to campaigns and adsets

Revision ID: b7d3e1f2a9c5
Revises: a3f9b2c1d4e7
Create Date: 2026-04-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = 'b7d3e1f2a9c5'
down_revision = 'a3f9b2c1d4e7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('facebook_campaigns',
        sa.Column('budget_schedule_type', sa.String(), nullable=True, server_default='DAILY'))
    op.add_column('facebook_campaigns',
        sa.Column('lifetime_budget', sa.Integer(), nullable=True))
    op.add_column('facebook_campaigns',
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True))

    op.add_column('facebook_adsets',
        sa.Column('budget_schedule_type', sa.String(), nullable=True, server_default='DAILY'))
    op.add_column('facebook_adsets',
        sa.Column('lifetime_budget', sa.Integer(), nullable=True))
    op.add_column('facebook_adsets',
        sa.Column('end_time', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('facebook_adsets', 'end_time')
    op.drop_column('facebook_adsets', 'lifetime_budget')
    op.drop_column('facebook_adsets', 'budget_schedule_type')

    op.drop_column('facebook_campaigns', 'end_time')
    op.drop_column('facebook_campaigns', 'lifetime_budget')
    op.drop_column('facebook_campaigns', 'budget_schedule_type')
