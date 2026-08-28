"""add capi_quality_snapshots table

Revision ID: y3u1v7w8x0t6
Revises: x2t0u6v7w9s5
Create Date: 2026-08-28

Daily snapshot of Meta's Dataset Quality API (Event Match Quality), one row
per (pixel, account, event, day) — Meta returns EMQ per event_name with no
aggregate row, so every event is stored rather than picking one arbitrarily.
Lets CAPI match quality be compared across ad accounts over time — e.g. the
advertiser-run CAPI on RHO 4 vs. Everflow's CAPI on the other RHO accounts.
See backend/app/services/capi_quality_service.py and models.CapiQualitySnapshot.
"""
from alembic import op
import sqlalchemy as sa


revision = 'y3u1v7w8x0t6'
down_revision = 'x2t0u6v7w9s5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # init_db.py runs Base.metadata.create_all() before alembic, so on a real
    # deploy this table likely already exists. Keep columns in sync with
    # models.CapiQualitySnapshot — if they drift, create_all()'s version wins
    # silently.
    if not sa.inspect(bind).has_table('capi_quality_snapshots'):
        op.create_table(
            'capi_quality_snapshots',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('pixel_id', sa.String(), nullable=False, index=True),
            sa.Column('pixel_name', sa.String(), nullable=True),
            sa.Column('fb_account_id', sa.String(), nullable=True, index=True),
            sa.Column('account_name', sa.String(), nullable=True),
            sa.Column('event_name', sa.String(), nullable=True),
            sa.Column('snapshot_date', sa.Date(), nullable=False, index=True),
            sa.Column('event_match_quality', sa.Numeric(precision=4, scale=2), nullable=True),
            sa.Column('acr', sa.Numeric(precision=6, scale=2), nullable=True),
            sa.Column('event_coverage', sa.Numeric(precision=6, scale=2), nullable=True),
            sa.Column('data_freshness', sa.String(), nullable=True),
            sa.Column('match_key_feedback', sa.JSON(), nullable=True),
            sa.Column('diagnostics', sa.JSON(), nullable=True),
            sa.Column('fetch_error', sa.Text(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.UniqueConstraint(
                'pixel_id', 'fb_account_id', 'event_name', 'snapshot_date',
                name='uq_capi_quality_pixel_account_event_date',
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('capi_quality_snapshots'):
        op.drop_table('capi_quality_snapshots')
