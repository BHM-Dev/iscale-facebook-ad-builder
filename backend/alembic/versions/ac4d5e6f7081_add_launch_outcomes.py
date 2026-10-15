"""add launch_outcomes table

Revision ID: ac4d5e6f7081
Revises: ab3c4d5e6f70
Create Date: 2026-10-15

One row per bulk-launch run so partial/failed launches alert immediately.
See models.LaunchOutcome and app/api/v1/launch_outcomes.py.
"""
from alembic import op
import sqlalchemy as sa


revision = 'ac4d5e6f7081'
down_revision = 'ab3c4d5e6f70'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # init_db.py's create_all() usually creates this first; keep in sync with models.LaunchOutcome.
    if sa.inspect(bind).has_table('launch_outcomes'):
        return
    op.create_table(
        'launch_outcomes',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), index=True),
        sa.Column('user_email', sa.String(), nullable=True),
        sa.Column('ad_account_id', sa.String(), nullable=True, index=True),
        sa.Column('campaign_name', sa.String(), nullable=True),
        sa.Column('adset_name', sa.String(), nullable=True),
        sa.Column('outcome', sa.String(), nullable=False, index=True),
        sa.Column('attempted', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('errors', sa.JSON(), nullable=True),
        sa.Column('meta', sa.JSON(), nullable=True),
        sa.Column('alerted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('investigated_at', sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('launch_outcomes'):
        op.drop_table('launch_outcomes')
