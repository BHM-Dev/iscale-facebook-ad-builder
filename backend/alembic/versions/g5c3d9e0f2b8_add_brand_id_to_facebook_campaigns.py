"""Add brand_id to facebook_campaigns for Remix drawer brand auto-fill.

Revision ID: g5c3d9e0f2b8
Revises: f4b2c8d9e1a7
Create Date: 2026-05-10

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'g5c3d9e0f2b8'
down_revision: Union[str, Sequence[str], None] = 'f4b2c8d9e1a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE facebook_campaigns
        ADD COLUMN IF NOT EXISTS brand_id VARCHAR REFERENCES brands(id) ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE facebook_campaigns DROP COLUMN IF EXISTS brand_id")
