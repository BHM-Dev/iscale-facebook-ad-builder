"""Merge heads — no-op, retained so production DB stamp remains valid.

The two original parent revisions (c4f8a2d1e6b9, add_page_fields_001) were
squashed into the baseline migration (1b02d74254e5). This file is kept solely
because the production database has d8f2e1a7b4c9 stamped as its current
revision. Removing it causes alembic to fail on startup with
"Can't locate revision identified by 'd8f2e1a7b4c9'".

Revision ID: d8f2e1a7b4c9
Revises: 1b02d74254e5
Create Date: 2026-04-17

"""
from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = 'd8f2e1a7b4c9'
down_revision: Union[str, Sequence[str], None] = '1b02d74254e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op — schema already applied via baseline migration."""
    pass


def downgrade() -> None:
    """No-op — nothing to undo."""
    pass
