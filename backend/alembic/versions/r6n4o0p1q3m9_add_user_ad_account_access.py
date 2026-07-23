"""add per-user ad account access (visibility scoping)

Revision ID: r6n4o0p1q3m9
Revises: q5m3n9o0p2l8
Create Date: 2026-07-21

Per-user allow-list of Meta ad accounts. Non-breaking default: a user with NO
rows here is unrestricted (sees all accounts), as are superusers. Assigning any
rows restricts the user to exactly those accounts. Enforced server-side in the
facebook routes, not just hidden in the UI.
"""
from alembic import op
import sqlalchemy as sa


revision = 'r6n4o0p1q3m9'
down_revision = 'q5m3n9o0p2l8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('user_ad_accounts'):
        return
    op.create_table(
        'user_ad_accounts',
        sa.Column('id', sa.String(), primary_key=True),
        sa.Column('user_id', sa.String(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('ad_account_id', sa.String(), nullable=False),  # Meta act_... id
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', 'ad_account_id', name='uq_user_ad_account'),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('user_ad_accounts'):
        op.drop_table('user_ad_accounts')
