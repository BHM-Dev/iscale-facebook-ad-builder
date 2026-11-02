"""add action_proposals and proposal_events (approvals queue)

Revision ID: ad5e6f708192
Revises: ac4d5e6f7081
Create Date: 2026-11-02

See models.ActionProposal / models.ProposalEvent and app/services/proposal_service.py.
"""
from alembic import op
import sqlalchemy as sa


revision = 'ad5e6f708192'
down_revision = 'ac4d5e6f7081'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # init_db.py's create_all() usually creates these first; keep in sync with models.
    if not sa.inspect(bind).has_table('action_proposals'):
        op.create_table(
            'action_proposals',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('fb_account_id', sa.String(), nullable=False),
            sa.Column('fb_adset_id', sa.String(), nullable=False, index=True),
            sa.Column('adset_name', sa.String(), nullable=True),
            sa.Column('trigger_key', sa.String(), nullable=False),
            sa.Column('trigger_keys', sa.JSON(), nullable=True),
            sa.Column('action', sa.String(), nullable=False),
            sa.Column('action_params', sa.JSON(), nullable=True),
            sa.Column('evidence', sa.JSON(), nullable=True),
            sa.Column('status', sa.String(), nullable=False, server_default='open', index=True),
            sa.Column('status_reason', sa.String(), nullable=True),
            sa.Column('decided_by', sa.String(), nullable=True),
            sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
            sa.Column('dismiss_reason', sa.String(), nullable=True),
            sa.Column('dismiss_note', sa.Text(), nullable=True),
            sa.Column('execution_result', sa.JSON(), nullable=True),
            sa.Column('outcome_3d', sa.JSON(), nullable=True),
            sa.Column('soft_tags', sa.JSON(), nullable=True),
            sa.Column('variant', sa.String(), nullable=True),
            sa.Column('geo', sa.String(), nullable=True),
        )
        op.create_index('ix_action_proposals_account_status', 'action_proposals', ['fb_account_id', 'status'])
    if not sa.inspect(bind).has_table('proposal_events'):
        op.create_table(
            'proposal_events',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
            sa.Column('proposal_id', sa.String(), sa.ForeignKey('action_proposals.id', ondelete='CASCADE'), nullable=True, index=True),
            sa.Column('event', sa.String(), nullable=False),
            sa.Column('user_email', sa.String(), nullable=True),
            sa.Column('props', sa.JSON(), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('proposal_events'):
        op.drop_table('proposal_events')
    if sa.inspect(bind).has_table('action_proposals'):
        op.drop_table('action_proposals')
