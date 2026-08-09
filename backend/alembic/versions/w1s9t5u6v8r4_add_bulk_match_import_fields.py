"""add bulk match import fields

Revision ID: w1s9t5u6v8r4
Revises: v0r8s4t5u7q3
Create Date: 2026-08-09

Adds two nullable columns to facebook_ads for the Bulk Match Import flow:
secondary_image_url (the matched 9x16 asset, reserved for a future
placement-customization feature — not used to build any Meta creative today)
and ad_number (traceability back to the source batch's copy doc, e.g. "AD 12").
"""
from alembic import op


revision = 'w1s9t5u6v8r4'
down_revision = 'v0r8s4t5u7q3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS secondary_image_url VARCHAR")
    op.execute("ALTER TABLE facebook_ads ADD COLUMN IF NOT EXISTS ad_number VARCHAR")


def downgrade() -> None:
    op.execute("ALTER TABLE facebook_ads DROP COLUMN IF EXISTS ad_number")
    op.execute("ALTER TABLE facebook_ads DROP COLUMN IF EXISTS secondary_image_url")
