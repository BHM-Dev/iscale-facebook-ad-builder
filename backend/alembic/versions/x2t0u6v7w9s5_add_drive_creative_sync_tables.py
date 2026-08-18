"""add drive creative sync tables

Revision ID: x2t0u6v7w9s5
Revises: w1s9t5u6v8r4
Create Date: 2026-08-18

Adds drive_assets (creative synced from Joel's shared Google Drive folder into
R2, see backend/app/services/drive_sync_service.py) and drive_sync_state (a
singleton key/value checkpoint for the Drive changes.list startPageToken, so
incremental sync never has to re-scan the whole folder tree).
"""
from alembic import op
import sqlalchemy as sa


revision = 'x2t0u6v7w9s5'
down_revision = 'w1s9t5u6v8r4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # init_db.py runs Base.metadata.create_all() before alembic, so on a real
    # deploy these tables likely already exist. Keep columns in sync with
    # models.DriveAsset / models.DriveSyncState — if they drift, create_all()'s
    # version wins silently.
    if not sa.inspect(bind).has_table('drive_assets'):
        op.create_table(
            'drive_assets',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('drive_file_id', sa.String(), nullable=False, unique=True, index=True),
            sa.Column('brand_id', sa.String(), sa.ForeignKey('brands.id', ondelete='CASCADE'), nullable=False, index=True),
            sa.Column('product_id', sa.String(), sa.ForeignKey('products.id', ondelete='SET NULL'), nullable=True, index=True),
            sa.Column('format', sa.String(), nullable=False),
            sa.Column('folder_path', sa.String(), nullable=True),
            sa.Column('file_name', sa.String(), nullable=False),
            sa.Column('r2_key', sa.String(), nullable=False),
            sa.Column('thumbnail_r2_key', sa.String(), nullable=True),
            sa.Column('drive_modified_time', sa.DateTime(timezone=True), nullable=False),
            sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('archived', sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column('soft_tags', sa.String(), nullable=True),
            sa.Column('variant', sa.String(), nullable=True),
            sa.Column('geo', sa.String(), nullable=True),
        )

    if not sa.inspect(bind).has_table('drive_sync_state'):
        op.create_table(
            'drive_sync_state',
            sa.Column('key', sa.String(), primary_key=True),
            sa.Column('value', sa.Text(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('drive_sync_state'):
        op.drop_table('drive_sync_state')
    if sa.inspect(bind).has_table('drive_assets'):
        op.drop_table('drive_assets')
