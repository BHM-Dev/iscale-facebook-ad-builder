"""Add brand_id to facebook_adsets for per-adset brand assignment.

Revision ID: h6d4e0f1g3c9
Revises: g5c3d9e0f2b8
Create Date: 2026-05-10

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'h6d4e0f1g3c9'
down_revision: Union[str, Sequence[str], None] = 'g5c3d9e0f2b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE facebook_adsets
        ADD COLUMN IF NOT EXISTS brand_id VARCHAR REFERENCES brands(id) ON DELETE SET NULL
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE facebook_adsets DROP COLUMN IF EXISTS brand_id")
