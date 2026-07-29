"""add pnl_month_snapshots

Revision ID: u9q7r3s4t6p2
Revises: t8p6q2r3s5o1
Create Date: 2026-07-29

Frozen external figures for closed months, per ad account. /pnl/months was
re-fetching six months of Meta and revenue data on every page load (23s in
production) even though a closed month never changes.

Stores only the external data. Costs are NOT snapshotted — they come from
pnl_cost_entries, which the user edits, so they are recomputed from the ledger
on every read and past months pick up newly added retainers.
"""
from alembic import op
import sqlalchemy as sa


revision = 'u9q7r3s4t6p2'
down_revision = 't8p6q2r3s5o1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # init_db.py runs Base.metadata.create_all() before alembic, so on a real
    # deploy the table already exists. Keep these columns in sync with
    # models.PnlMonthSnapshot — if they drift, create_all()'s version wins
    # silently.
    if sa.inspect(bind).has_table('pnl_month_snapshots'):
        return
    op.create_table(
        'pnl_month_snapshots',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('ad_account_id', sa.String(), nullable=False, index=True),
        sa.Column('month', sa.Date(), nullable=False),
        sa.Column('date_from', sa.Date(), nullable=False),
        sa.Column('date_to', sa.Date(), nullable=False),
        sa.Column('spend', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('revenue', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('unattributed_revenue', sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column('conversions', sa.Integer(), nullable=True),
        sa.Column('revenue_source', sa.String(), nullable=True),
        sa.Column('unmapped_adsets', sa.Integer(), nullable=True),
        sa.Column('event_breakdown', sa.JSON(), nullable=True),
        sa.Column('synced_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('synced_by', sa.String(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.UniqueConstraint('ad_account_id', 'month', name='uq_pnl_month_snapshot'),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('pnl_month_snapshots'):
        op.drop_table('pnl_month_snapshots')
