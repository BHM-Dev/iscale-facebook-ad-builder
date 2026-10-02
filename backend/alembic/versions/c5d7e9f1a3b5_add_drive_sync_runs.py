"""add drive_sync_runs audit table

Revision ID: c5d7e9f1a3b5
Revises: a4b6c8d0e2f4
Create Date: 2026-10-02

One row per Drive sync / reconcile / copy-refresh run, so a run's outcome
survives the container recreate that wipes stdout on every deploy.
"""
from alembic import op
import sqlalchemy as sa


revision = 'c5d7e9f1a3b5'
down_revision = 'a4b6c8d0e2f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('drive_sync_runs'):
        return
    op.create_table(
        'drive_sync_runs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('processed', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('updated', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('archived', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('errors', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error_summary', sa.String(), nullable=True),
        sa.Column('triggered_by', sa.String(), nullable=True),
        sa.Column('package_folder_id', sa.String(), nullable=True),
        sa.Column('token_before', sa.String(), nullable=True),
        sa.Column('token_after', sa.String(), nullable=True),
        sa.Column('meta', sa.Text(), nullable=True),
    )
    op.create_index('ix_drive_sync_runs_kind', 'drive_sync_runs', ['kind'])
    op.create_index('ix_drive_sync_runs_started_at', 'drive_sync_runs', ['started_at'])


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS drive_sync_runs")
