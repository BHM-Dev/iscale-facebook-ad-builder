"""Merge heads: special_ad_categories + add_page_fields_brand_scraped_ads

Revision ID: d8f2e1a7b4c9
Revises: c4f8a2d1e6b9, add_page_fields_001
Create Date: 2026-04-17

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'd8f2e1a7b4c9'
down_revision: Union[str, Sequence[str], None] = ('c4f8a2d1e6b9', 'add_page_fields_001')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op merge migration."""
    pass


def downgrade() -> None:
    """No-op merge migration."""
    pass
