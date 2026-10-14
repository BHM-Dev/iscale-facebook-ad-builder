"""add meta_call_stats table

Revision ID: ab3c4d5e6f70
Revises: aa2b3c4d5e6f
Create Date: 2026-10-14

Hourly Meta Graph API call counts by caller/endpoint, so an app-level throttle
can be attributed after the fact. See app/services/meta_call_telemetry.py.
"""
from alembic import op
import sqlalchemy as sa


revision = 'ab3c4d5e6f70'
down_revision = 'aa2b3c4d5e6f'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # init_db.py runs Base.metadata.create_all() before alembic, so the table
    # usually exists already. Keep columns in sync with models.MetaCallStat.
    if sa.inspect(bind).has_table('meta_call_stats'):
        return
    op.create_table(
        'meta_call_stats',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('hour_start', sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column('caller', sa.String(), nullable=False),
        sa.Column('method', sa.String(), nullable=False),
        sa.Column('endpoint', sa.String(), nullable=False),
        sa.Column('calls', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('errors', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('throttles', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('total_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('app_usage_max', sa.Integer(), nullable=True),
        sa.Column('account_usage_max', sa.Integer(), nullable=True),
        sa.UniqueConstraint('hour_start', 'caller', 'method', 'endpoint', name='uq_meta_call_stats_bucket'),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('meta_call_stats'):
        op.drop_table('meta_call_stats')
