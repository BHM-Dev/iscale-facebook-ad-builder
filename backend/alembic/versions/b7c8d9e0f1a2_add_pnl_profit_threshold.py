"""add profit_threshold to pnl_cost_entries

Revision ID: b7c8d9e0f1a2
Revises: f2a1b0c9d8e7
Create Date: 2026-09-29

pct_of_profit commissions (Abel's 5%) pay $0 until the period's net profit
reaches this dollar threshold.
"""
from alembic import op


revision = 'b7c8d9e0f1a2'
down_revision = 'f2a1b0c9d8e7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE pnl_cost_entries ADD COLUMN IF NOT EXISTS profit_threshold NUMERIC(12, 2)")


def downgrade() -> None:
    op.execute("ALTER TABLE pnl_cost_entries DROP COLUMN IF EXISTS profit_threshold")
