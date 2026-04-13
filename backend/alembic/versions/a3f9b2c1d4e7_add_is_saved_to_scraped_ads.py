"""add_is_saved_to_scraped_ads

Revision ID: a3f9b2c1d4e7
Revises: f4be6367be6c
Create Date: 2026-04-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f9b2c1d4e7'
down_revision: Union[str, Sequence[str], None] = 'f4be6367be6c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_saved flag to scraped_ads for user-curated research library."""
    op.add_column('scraped_ads', sa.Column('is_saved', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    """Remove is_saved flag from scraped_ads."""
    op.drop_column('scraped_ads', 'is_saved')
