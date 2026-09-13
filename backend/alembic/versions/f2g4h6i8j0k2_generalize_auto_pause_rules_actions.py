"""generalize auto_pause_rules from pause-only to a multi-action rules engine

Revision ID: f2g4h6i8j0k2
Revises: z1a2b3c4d5e6
Create Date: 2026-09-13

Per AdBuilder-BulkRules-Feature-Brief.md: generalizes the existing auto-pause
rules engine to a small MVP action set (pause / notify / increase_budget /
decrease_budget) instead of pause-only, and adds the rule-trigger audit log
that was already on the "Still pending" list in CLAUDE.md.

- `action` on auto_pause_rules: defaults to 'pause' for every existing row,
  so no behavior changes for rules created before this migration.
- `budget_adjust_pct`: NULL for pause/notify rules, set for budget rules.
- `auto_pause_rule_logs`: append-only history of every rule that actually
  fired, across all action types — distinct from
  auto_pause_rules.triggered_at/trigger_reason, which only remember the
  most recent fire per rule.
"""
from alembic import op
import sqlalchemy as sa


revision = 'f2g4h6i8j0k2'
down_revision = 'z1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    op.execute("ALTER TABLE auto_pause_rules ADD COLUMN IF NOT EXISTS action VARCHAR NOT NULL DEFAULT 'pause'")
    op.execute("ALTER TABLE auto_pause_rules ADD COLUMN IF NOT EXISTS budget_adjust_pct INTEGER")

    # init_db.py runs Base.metadata.create_all() before alembic — on a real deploy this
    # table likely already exists. Guard matches the established convention (see
    # x2t0u6v7w9s5_add_drive_creative_sync_tables.py).
    if not sa.inspect(bind).has_table('auto_pause_rule_logs'):
        op.create_table(
            'auto_pause_rule_logs',
            sa.Column('id', sa.String(), primary_key=True),
            sa.Column('rule_id', sa.String(), sa.ForeignKey('auto_pause_rules.id', ondelete='SET NULL'), nullable=True, index=True),
            sa.Column('adset_id', sa.String(), sa.ForeignKey('facebook_adsets.id', ondelete='SET NULL'), nullable=True, index=True),
            sa.Column('fb_adset_id', sa.String(), nullable=True),
            sa.Column('action', sa.String(), nullable=False),
            sa.Column('metric', sa.String(), nullable=False),
            sa.Column('metric_value', sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column('threshold', sa.Integer(), nullable=False),
            sa.Column('spend', sa.Numeric(precision=10, scale=2), nullable=True),
            sa.Column('result', sa.String(), nullable=False),
            sa.Column('detail', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False, index=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('auto_pause_rule_logs'):
        op.drop_table('auto_pause_rule_logs')
    op.execute("ALTER TABLE auto_pause_rules DROP COLUMN IF EXISTS budget_adjust_pct")
    op.execute("ALTER TABLE auto_pause_rules DROP COLUMN IF EXISTS action")
